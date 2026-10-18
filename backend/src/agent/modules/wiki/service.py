"""MOD-10 Wiki 관리: BuildWiki → ValidateBuild(자동 대조) → 의미 검수 → PublishWiki, GetCandidates.

- 실시간 대화 중에는 빌드하지 않는다(운영 CLI 전용, ops.wiki_build).
- Wiki는 corpus snapshot 하나에 묶인다. 다른 corpus의 run에는 쓰지 않는다(stale).
- page는 기여 원문 판본을 모두 현재 사용자가 읽을 수 있을 때만 후보가 된다(교집합, MOD-05 판정).
- 게시는 검수된 page만 한 트랜잭션으로 snapshot·포인터를 바꾼다. 실패하면 이전 게시본이 그대로다.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from agent.modules.knowledge.service import KnowledgeService
from agent.modules.knowledge.tables import EMBEDDING_DIM
from agent.modules.model_integration.gemini_embedding import MAX_BATCH, format_input
from agent.modules.model_integration.ports import (
    ChatModel,
    EmbeddingConfig,
    EmbeddingModel,
    ModelCallError,
    ModelConfig,
    ModelFailure,
    ModelMessage,
    ModelRequest,
    Usage,
)
from agent.modules.wiki import build as wb
from agent.modules.wiki.contracts import BuildReport, CandidateResult, CheckedPage, TopicPlan, WikiCandidate
from agent.modules.wiki.tables import (
    POINTER,
    wiki_builds,
    wiki_claims,
    wiki_embeddings,
    wiki_pages,
    wiki_pointer,
    wiki_snapshot_members,
    wiki_snapshots,
    wiki_source_links,
)
from agent.shared.actor import ActorContext
from agent.shared.clock import Clock
from agent.shared.errors import AppError, ErrorCode

WIKI_CANDIDATE_LIMIT = 5
BUILD_TIMEOUT_S = 120.0  # 오프라인 빌드 호출 하나의 시간 상한(온라인 20초와 별개)
MAX_GENERATION_ATTEMPTS = 2  # 첫 생성 + 원문 대조·형식 문제를 알려 준 재생성 1회
MAX_TRANSIENT_RETRIES = 1  # 일시 오류(rate limit·연결) 재시도. 재생성 기회와 따로 센다.
REVIEWER_KINDS = frozenset({"human", "model"})
_PUBLISH_LOCK = 0x5749_4B49  # 게시 직렬화용 advisory lock 키("WIKI")


class WikiPublishRejected(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons[:5]))
        self.reasons = reasons


@dataclass
class _Tally:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_usage_calls: int = 0
    embed_requests: int = 0
    embed_inputs: int = 0
    embed_failed_requests: int = 0
    model_ids: set[str] = field(default_factory=set)

    def add(self, usage: Usage, model_id: str | None = None) -> None:
        self.calls += 1
        if usage.input_tokens is None or usage.output_tokens is None or not usage.complete:
            self.unknown_usage_calls += 1
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        if model_id:
            self.model_ids.add(model_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "unknown_usage_calls": self.unknown_usage_calls,
            "embed_requests": self.embed_requests,
            "embed_inputs": self.embed_inputs,
            "embed_failed_requests": self.embed_failed_requests,
            "model_ids": sorted(self.model_ids),
        }


def _operator(actor: ActorContext) -> None:
    if actor.source != "operator_cli" or "ops.wiki_build" not in actor.capabilities:
        raise AppError(ErrorCode.ACTION_NOT_ALLOWED)


class WikiService:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        knowledge: KnowledgeService,
        *,
        chat: ChatModel | None = None,
        embedder: EmbeddingModel | None = None,
        model_config: ModelConfig | None = None,
        embedding_model: str = "gemini-embedding-2",
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._knowledge = knowledge
        self._chat = chat
        self._embedder = embedder
        self._model_config = model_config
        self._embedding_model = embedding_model

    # --- 빌드 ---

    async def build(
        self, operator: ActorContext, plan: TopicPlan, *, corpus_snapshot_id: str, scope: str = "release"
    ) -> BuildReport:
        """BuildWiki + ValidateBuild. 원문 대조를 통과한 page만 임베딩하고 검수 대기(pending)로 둔다."""
        _operator(operator)
        if self._chat is None or self._embedder is None or self._model_config is None:
            raise AppError(ErrorCode.MODEL_NOT_CONFIGURED)
        if plan.status != "reviewed":
            raise AppError(ErrorCode.INVALID_REQUEST, details={"field_names": ["topic_plan"]})
        sources = await self._knowledge.read_build_sources(operator, corpus_snapshot_id)
        present = {e.document_key for e in sources}
        planned = {key for topic in plan.topics for key in topic.document_keys}
        unknown = sorted(planned - present)
        if unknown:
            raise AppError(ErrorCode.INVALID_REQUEST, details={"field_names": ["topic_plan.document_keys"]})
        now = self._clock.now()
        build_id = uuid.uuid4()
        tally = _Tally()
        async with self._engine.begin() as conn:
            await conn.execute(
                wiki_builds.insert().values(
                    build_id=build_id,
                    corpus_snapshot_id=uuid.UUID(corpus_snapshot_id),
                    scope=scope,
                    topic_plan_hash=plan.plan_hash,
                    config_id=wb.CONFIG_ID,
                    prompt_version=wb.PROMPT_VERSION,
                    model_id=self._model_config.model,
                    embedding_model=self._embedding_model,
                    status="draft",
                    report={},
                    usage={},
                    created_by=operator.user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        page_plans = [p for topic in plan.topics for p in wb.plan_pages(topic, sources)]
        try:
            return await self._build_pages(build_id, corpus_snapshot_id, page_plans, present, planned, tally)
        except Exception:
            # 빌드 도중 예외: draft로 남기지 않고 실패와 지금까지의 사용량을 기록한다(비용을 잃지 않게).
            async with self._engine.begin() as conn:
                await conn.execute(
                    update(wiki_builds)
                    .where(wiki_builds.c.build_id == build_id)
                    .values(
                        status="failed",
                        report={"error": "build_exception"},
                        usage=tally.as_dict(),
                        updated_at=self._clock.now(),
                    )
                )
            raise

    async def _build_pages(
        self, build_id, corpus_snapshot_id, page_plans, present, planned, tally
    ) -> BuildReport:
        valid_pages: list[tuple[uuid.UUID, CheckedPage]] = []
        excluded: list[dict[str, Any]] = []
        for page_plan in page_plans:
            page_id = uuid.uuid4()
            checked, usage = await self._generate(page_plan, tally)
            await self._save_page(build_id, page_id, page_plan, checked, usage)
            if checked.valid:
                valid_pages.append((page_id, checked))
            else:
                excluded.append(
                    {
                        "page_id": str(page_id),
                        "topic_key": page_plan.topic.topic_key,
                        "segment_key": page_plan.segment_key,
                        "acl_class": page_plan.acl_class,
                        "problems": list(checked.problems[:20]),
                    }
                )
        embed_problem = await self._embed(valid_pages, tally) if valid_pages else None
        status = "validated" if valid_pages and embed_problem is None else "failed"
        report = BuildReport(
            build_id=str(build_id),
            status=status,
            corpus_snapshot_id=corpus_snapshot_id,
            pages_planned=len(page_plans),
            pages_valid=len(valid_pages),
            pages_excluded=len(excluded),
            uncovered_document_keys=tuple(sorted(present - planned)),
            excluded=tuple(excluded),
            usage=tally.as_dict(),
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                update(wiki_builds)
                .where(wiki_builds.c.build_id == build_id)
                .values(
                    status=status,
                    report={
                        "pages_planned": report.pages_planned,
                        "pages_valid": report.pages_valid,
                        "pages_excluded": report.pages_excluded,
                        "uncovered_document_keys": list(report.uncovered_document_keys),
                        "excluded": list(report.excluded),
                        "embedding_problem": embed_problem,
                    },
                    usage=report.usage,
                    updated_at=self._clock.now(),
                )
            )
        return report

    async def _generate(self, plan, tally: _Tally) -> tuple[CheckedPage, dict[str, Any]]:
        if self._chat is None or self._model_config is None:
            raise AppError(ErrorCode.MODEL_NOT_CONFIGURED)
        usage = _Tally()
        if wb.input_tokens(plan) > wb.MAX_INPUT_TOKENS:
            return CheckedPage("", "", (), ("input_too_large",)), usage.as_dict()
        feedback: tuple[str, ...] = ()
        checked = CheckedPage("", "", (), ("not_generated",))
        attempts = transient = 0
        while attempts < MAX_GENERATION_ATTEMPTS:
            request = ModelRequest(
                purpose="wiki_build",
                messages=(ModelMessage(role="user", text=wb.user_text(plan, feedback)),),
                tools=(),
                output_contract=wb.OUTPUT_SCHEMA,
                timeout_s=BUILD_TIMEOUT_S,
                model_config=self._model_config,
                system=wb.SYSTEM_PROMPT,
            )
            try:
                response = await self._chat.complete_once(request)
            except ModelCallError as error:
                tally.add(error.usage)
                usage.add(error.usage)
                checked = CheckedPage("", "", (), (f"model_error:{error.kind.value}",))
                if error.kind is ModelFailure.OUTPUT_INVALID:
                    # 잘린 출력·깨진 JSON도 내용 문제처럼 알려 주고 한 번 더 쓰게 한다.
                    attempts += 1
                    feedback = ("출력이 형식에 맞지 않거나 길이 때문에 잘렸다. 주장 수를 줄여 짧게 쓴다.",)
                    continue
                if error.retryable and transient < MAX_TRANSIENT_RETRIES:
                    transient += 1
                    continue
                break
            attempts += 1
            tally.add(response.usage, response.model_id)
            usage.add(response.usage, response.model_id)
            checked = wb.check_output(response.final_candidate, plan)
            if checked.valid:
                break
            feedback = checked.problems
        return checked, usage.as_dict()

    async def _save_page(self, build_id, page_id, plan, checked: CheckedPage, usage) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                wiki_pages.insert().values(
                    page_id=page_id,
                    build_id=build_id,
                    topic_key=plan.topic.topic_key,
                    segment_key=plan.segment_key,
                    acl_class=plan.acl_class,
                    # 미게시 page에 주제 제목을 채우지 않는다(다른 권한 등급 문서 이름이 섞일 수 있다).
                    title=checked.title,
                    summary=checked.summary,
                    search_text=wb.search_text(checked) if checked.valid else "",
                    valid_from=plan.valid_from,
                    valid_to=plan.valid_to,
                    knowledge_from=plan.knowledge_from,
                    knowledge_to=plan.knowledge_to,
                    contributor_edition_ids=list(plan.edition_ids),
                    source_hash=wb.source_hash(plan),
                    status="valid" if checked.valid else "excluded",
                    problems=list(checked.problems),
                    review_status="pending",
                    review=None,
                    usage=usage,
                )
            )
            if not checked.valid:
                return
            for ordinal, claim in enumerate(checked.claims, start=1):
                claim_id = uuid.uuid4()
                await conn.execute(
                    wiki_claims.insert().values(
                        claim_id=claim_id, page_id=page_id, ordinal=ordinal, kind=claim.kind, text=claim.text
                    )
                )
                for j, link in enumerate(claim.links, start=1):
                    await conn.execute(
                        wiki_source_links.insert().values(
                            link_id=uuid.uuid4(),
                            claim_id=claim_id,
                            page_id=page_id,
                            ordinal=j,
                            edition_id=uuid.UUID(link.edition_id),
                            passage_id=uuid.UUID(link.passage_id),
                            quote=link.quote,
                        )
                    )

    async def _embed(self, pages: list[tuple[uuid.UUID, CheckedPage]], tally: _Tally) -> str | None:
        """원문과 같은 모델·차원·입력 형식(document)으로 page 탐색 문장을 임베딩한다."""
        if self._embedder is None:
            raise AppError(ErrorCode.MODEL_NOT_CONFIGURED)
        config = EmbeddingConfig(self._embedding_model, EMBEDDING_DIM, "document")
        for start in range(0, len(pages), MAX_BATCH):
            batch = pages[start : start + MAX_BATCH]
            texts = tuple(format_input(wb.search_text(page), "document", page.title) for _, page in batch)
            tally.embed_requests += 1  # 시도한 요청을 센다(실패해도 무료 티어 한도를 썼을 수 있다)
            tally.embed_inputs += len(texts)
            try:
                result = await self._embedder.embed_once(texts, config, 60.0)
            except ModelCallError as error:
                tally.embed_failed_requests += 1
                return f"embedding_failed:{error.kind.value}"
            async with self._engine.begin() as conn:
                await conn.execute(
                    wiki_embeddings.insert(),
                    [
                        {"page_id": page_id, "model": result.model_id, "embedding": vector}
                        for (page_id, _), vector in zip(batch, result.vectors, strict=True)
                    ],
                )
        return None

    # --- 검수·게시 ---

    async def review_pages(self, build_id: str) -> list[dict[str, Any]]:
        """의미 검수용 내보내기: page·주장·인용·원문 passage ID(검수자가 원문과 대조한다)."""
        async with self._engine.connect() as conn:
            pages = (
                await conn.execute(
                    select(wiki_pages)
                    .where(wiki_pages.c.build_id == uuid.UUID(build_id))
                    .order_by(wiki_pages.c.topic_key, wiki_pages.c.segment_key, wiki_pages.c.acl_class)
                )
            ).all()
            claims = (
                await conn.execute(
                    select(wiki_claims).where(wiki_claims.c.page_id.in_([p.page_id for p in pages]))
                )
            ).all()
            links = (
                await conn.execute(
                    select(wiki_source_links).where(
                        wiki_source_links.c.page_id.in_([p.page_id for p in pages])
                    )
                )
            ).all()
        by_claim: dict[uuid.UUID, list[Any]] = {}
        for link in links:
            by_claim.setdefault(link.claim_id, []).append(link)
        by_page: dict[uuid.UUID, list[Any]] = {}
        for claim in sorted(claims, key=lambda c: c.ordinal):
            by_page.setdefault(claim.page_id, []).append(claim)
        return [
            {
                "page_id": str(p.page_id),
                "topic_key": p.topic_key,
                "segment_key": p.segment_key,
                "acl_class": p.acl_class,
                "status": p.status,
                "problems": p.problems,
                "title": p.title,
                "summary": p.summary,
                "review_status": p.review_status,
                "claims": [
                    {
                        "kind": c.kind,
                        "text": c.text,
                        "links": [
                            {"passage_id": str(link.passage_id), "quote": link.quote}
                            for link in sorted(by_claim.get(c.claim_id, []), key=lambda x: x.ordinal)
                        ],
                    }
                    for c in by_page.get(p.page_id, [])
                ],
            }
            for p in pages
        ]

    async def apply_review(
        self, operator: ActorContext, build_id: str, decisions: dict[str, dict[str, Any]]
    ) -> dict[str, int]:
        """의미 충실성 검수 결과를 page마다 기록한다(approved/rejected, 검수자·메모). 링크 검사와 별개다."""
        _operator(operator)
        counts = {"approved": 0, "rejected": 0, "ignored": 0}
        now = self._clock.now()
        async with self._engine.begin() as conn:
            build = (
                await conn.execute(
                    select(wiki_builds.c.status).where(wiki_builds.c.build_id == uuid.UUID(build_id))
                )
            ).first()
            if build is None or build.status != "validated":
                raise AppError(ErrorCode.INVALID_REQUEST, details={"field_names": ["build_id"]})
            valid = {
                str(row.page_id)
                for row in (
                    await conn.execute(
                        select(wiki_pages.c.page_id).where(
                            wiki_pages.c.build_id == uuid.UUID(build_id), wiki_pages.c.status == "valid"
                        )
                    )
                ).all()
            }
            for page_id, decision in decisions.items():
                verdict = decision.get("decision")
                reviewer = str(decision.get("reviewer") or "").strip()
                kind = decision.get("reviewer_kind")
                # 검수 주체(사람/모델)를 밝히지 않은 결정은 받지 않는다(D-48: 보고서에 모델 검수임을 밝힌다).
                if (
                    page_id not in valid
                    or verdict not in ("approved", "rejected")
                    or not reviewer
                    or kind not in REVIEWER_KINDS
                ):
                    counts["ignored"] += 1
                    continue
                await conn.execute(
                    update(wiki_pages)
                    .where(wiki_pages.c.page_id == uuid.UUID(page_id))
                    .values(
                        review_status=verdict,
                        review={
                            "reviewer": reviewer,
                            "reviewer_kind": kind,
                            "notes": decision.get("notes") or "",
                            "reviewed_at": now.isoformat(),
                        },
                    )
                )
                counts[verdict] += 1
        return counts

    async def publish(self, operator: ActorContext, build_id: str) -> dict[str, Any]:
        """PublishWiki: 검수가 끝난 build의 승인 page만 불변 snapshot으로 묶고 포인터를 바꾼다(원자적)."""
        _operator(operator)
        key = uuid.UUID(build_id)
        async with self._engine.begin() as conn:
            # 게시를 하나씩만 한다(동시에 두 build가 published가 되지 않게). 잠근 뒤 현재 corpus를 읽는다.
            await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PUBLISH_LOCK})
            current_corpus = await self._knowledge.current_snapshot()
            build = (
                await conn.execute(select(wiki_builds).where(wiki_builds.c.build_id == key).with_for_update())
            ).first()
            if build is None:
                raise WikiPublishRejected(["build 없음"])
            reasons = []
            if build.status != "validated":
                reasons.append(f"build 상태가 validated가 아니다({build.status})")
            if current_corpus is None or str(build.corpus_snapshot_id) != current_corpus:
                reasons.append("build의 corpus snapshot이 현재 게시본과 다르다(stale)")
            pages = (
                await conn.execute(
                    select(
                        wiki_pages.c.page_id, wiki_pages.c.review_status, wiki_embeddings.c.page_id.label("e")
                    )
                    .outerjoin(wiki_embeddings, wiki_embeddings.c.page_id == wiki_pages.c.page_id)
                    .where(wiki_pages.c.build_id == key, wiki_pages.c.status == "valid")
                )
            ).all()
            pending = [p for p in pages if p.review_status == "pending"]
            approved = [p for p in pages if p.review_status == "approved"]
            if pending:
                reasons.append(f"의미 검수가 끝나지 않은 page {len(pending)}개")
            if not approved:
                reasons.append("승인된 page가 없다")
            if any(p.e is None for p in approved):
                reasons.append("임베딩 없는 page가 있다")
            if reasons:
                raise WikiPublishRejected(reasons)
            now = self._clock.now()
            snapshot_id = uuid.uuid4()
            await conn.execute(
                wiki_snapshots.insert().values(
                    snapshot_id=snapshot_id,
                    build_id=key,
                    corpus_snapshot_id=build.corpus_snapshot_id,
                    page_count=len(approved),
                    created_by=operator.user_id,
                    created_at=now,
                )
            )
            await conn.execute(
                wiki_snapshot_members.insert(),
                [{"snapshot_id": snapshot_id, "page_id": p.page_id} for p in approved],
            )
            await conn.execute(
                update(wiki_builds)
                .where(wiki_builds.c.status == "published")
                .values(status="retired", updated_at=now)
            )
            await conn.execute(
                update(wiki_builds)
                .where(wiki_builds.c.build_id == key)
                .values(status="published", updated_at=now)
            )
            revision = await conn.scalar(
                insert(wiki_pointer)
                .values(name=POINTER, snapshot_id=snapshot_id, revision=1, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["name"],
                    set_={
                        "snapshot_id": snapshot_id,
                        "revision": wiki_pointer.c.revision + 1,
                        "updated_at": now,
                    },
                )
                .returning(wiki_pointer.c.revision)
            )
        return {
            "wiki_snapshot_id": str(snapshot_id),
            "page_count": len(approved),
            "pointer_revision": revision,
        }

    async def build_corpus(self, build_id: str) -> str | None:
        """build가 묶인 corpus snapshot(검수 파일은 현재 게시본이 아니라 이 corpus의 원문으로 만든다)."""
        async with self._engine.connect() as conn:
            value = await conn.scalar(
                select(wiki_builds.c.corpus_snapshot_id).where(wiki_builds.c.build_id == uuid.UUID(build_id))
            )
        return str(value) if value else None

    async def current_snapshot(self) -> str | None:
        async with self._engine.connect() as conn:
            value = await conn.scalar(
                select(wiki_pointer.c.snapshot_id).where(wiki_pointer.c.name == POINTER)
            )
        return str(value) if value else None

    async def status(self) -> dict[str, Any]:
        """GetBuildStatus: 게시 포인터·묶인 corpus·stale 여부(현재 corpus 게시본과 다르면 stale)."""
        current_corpus = await self._knowledge.current_snapshot()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(wiki_snapshots, wiki_pointer.c.revision)
                    .join(wiki_pointer, wiki_pointer.c.snapshot_id == wiki_snapshots.c.snapshot_id)
                    .where(wiki_pointer.c.name == POINTER)
                )
            ).first()
            builds = await conn.scalar(select(func.count()).select_from(wiki_builds))
        if row is None:
            return {"state": "not_ready", "builds": builds}
        stale = current_corpus is None or str(row.corpus_snapshot_id) != current_corpus
        return {
            "state": "stale" if stale else "ready",
            "wiki_snapshot_id": str(row.snapshot_id),
            "build_id": str(row.build_id),
            "corpus_snapshot_id": str(row.corpus_snapshot_id),
            "page_count": row.page_count,
            "pointer_revision": row.revision,
            "builds": builds,
        }

    # --- 후보 ---

    async def get_candidates(
        self,
        actor: ActorContext,
        query_vector: tuple[float, ...],
        *,
        corpus_snapshot_id: str,
        wiki_snapshot_id: str | None,
        as_of_date: date,
        knowledge_as_of: datetime,
        limit: int = WIKI_CANDIDATE_LIMIT,
    ) -> CandidateResult:
        """GetCandidates: run에 고정된 wiki snapshot에서 적용 시점이 맞고 기여 원문을 모두 읽을 수 있는 page.

        snapshot이 없으면 not_ready, run의 corpus와 다른 corpus에 묶였으면 stale이다(묵시적 재사용 금지).
        """
        if wiki_snapshot_id is None:
            return CandidateResult("not_ready", None)
        try:
            snapshot_key = uuid.UUID(wiki_snapshot_id)
        except ValueError:
            return CandidateResult("not_ready", None)
        async with self._engine.connect() as conn:
            bound = await conn.scalar(
                select(wiki_snapshots.c.corpus_snapshot_id).where(
                    wiki_snapshots.c.snapshot_id == snapshot_key
                )
            )
            if bound is None:
                return CandidateResult("not_ready", None)
            if str(bound) != corpus_snapshot_id:
                return CandidateResult("stale", wiki_snapshot_id)
            rows = (
                (
                    await conn.execute(
                        text(_CANDIDATE_SQL),
                        {
                            "snapshot_id": snapshot_key,
                            "query": "[" + ",".join(repr(float(v)) for v in query_vector) + "]",
                            "as_of_date": as_of_date,
                            "knowledge_as_of": knowledge_as_of,
                        },
                    )
                )
                .mappings()
                .all()
            )
        contributors = {e for row in rows for e in row["contributor_edition_ids"]}
        visible = await self._knowledge.visible_editions(
            actor, corpus_snapshot_id, contributors, knowledge_as_of=knowledge_as_of
        )
        # 기여 판본이 하나라도 안 보이면 page 전체를 숨긴다(합집합 공개 금지). 순위는 보이는 page 안에서만.
        chosen = [row for row in rows if set(row["contributor_edition_ids"]) <= visible][:limit]
        if not chosen:
            return CandidateResult("ready", wiki_snapshot_id)
        async with self._engine.connect() as conn:
            links = (
                await conn.execute(
                    select(wiki_source_links.c.page_id, wiki_source_links.c.passage_id)
                    .join(wiki_claims, wiki_claims.c.claim_id == wiki_source_links.c.claim_id)
                    .where(wiki_source_links.c.page_id.in_([row["page_id"] for row in chosen]))
                    .order_by(wiki_claims.c.ordinal, wiki_source_links.c.ordinal)
                )
            ).all()
        by_page: dict[str, list[str]] = {}
        for link in links:
            ids = by_page.setdefault(str(link.page_id), [])
            if str(link.passage_id) not in ids:
                ids.append(str(link.passage_id))
        return CandidateResult(
            "ready",
            wiki_snapshot_id,
            tuple(
                WikiCandidate(
                    page_id=str(row["page_id"]),
                    title=row["title"],
                    distance=float(row["distance"]),
                    passage_ids=tuple(by_page.get(str(row["page_id"]), ())),
                )
                for row in chosen
            ),
        )


_CANDIDATE_SQL = """
SELECT p.page_id, p.title, p.contributor_edition_ids, we.embedding <=> CAST(:query AS vector) AS distance
FROM wiki_snapshot_members m
JOIN wiki_pages p ON p.page_id = m.page_id
JOIN wiki_embeddings we ON we.page_id = p.page_id
WHERE m.snapshot_id = :snapshot_id
  AND (p.valid_from IS NULL OR p.valid_from <= CAST(:as_of_date AS date))
  AND (p.valid_to IS NULL OR CAST(:as_of_date AS date) < p.valid_to)
  AND p.knowledge_from <= :knowledge_as_of
  AND (p.knowledge_to IS NULL OR :knowledge_as_of < p.knowledge_to)
ORDER BY distance, p.page_id
"""


def plan_from_file(raw: str) -> TopicPlan:
    return wb.load_topic_plan(json.loads(raw))
