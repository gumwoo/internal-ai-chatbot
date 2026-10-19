"""MOD-11 raw 전략: SearchRequest(CT-13) → RetrievalResult(CT-14).

순서(docs/contracts/02-business-dates.md, 05-retrieval-assembly.md)
1. 날짜 검증: date_basis 닫힌 값, 사건 기준이면 as_of_date 필수(없으면 되묻기), 미래 90일 초과는 미지원.
2. LookupApplicableBasis: 날짜 필터 없이 관련 판본의 검수 메타데이터만 본다. 가장 가까운 규범이 사건 기준
   (교육 시작일 등)을 요구하는데 질문에 그 날짜가 없으면 되묻는다. 오늘 날짜로 금액부터 검색하지 않는다.
3. 검색: MOD-05가 권한·게시·지식 시점·규범 적용 구간으로 먼저 거른 후보만 받는다(raw_candidate_limit=20).
4. 조립: 후보마다 support_group(조항·FAQ 문항·표 전체)을 붙이고, 그룹을 대표 후보의 거리 순으로 정렬한다.
   같은 그룹은 한 번만 넣는다. 여러 검색의 최종 예산 조립은 MOD-02가 한다.
6. 경과조항 확장(D-40): 기본 판본에 검수된 transition_relations가 있으면, 사건 조건(검증된 사건 날짜들)이
   모두 확인되고 충족될 때만 반대편 판본의 조항을 같은 support_group에 source_role=transition으로 붙인다.
   알려진 조건이 이미 어긋나면 붙이지 않는다. 나머지 조건의 사건 날짜가 없으면 기본 판본 결과는 그대로 두고
   그 날짜를 묻는 후속 문구(transition_pending)를 싣는다(MOD-02가 답 끝에 붙인다). 같은 조항은 한 번만 붙인다.
7. 우선관계(D-40): 결과 문서의 authority_relations 중 대상 문서를 지금 볼 수 있는 것만 결과에 싣는다.
5. 규범 공백(T-17): 가장 가까운 규범이 이 날짜 기준에 맞는데 그 날짜를 포함하는 공개 판본이 없으면
   normative_gap을 표시한다. 안내 문서는 절차 확인용으로만 남기고, 결론 보류는 MOD-02가 한다.

B wiki_assisted(D-46, docs/13): 3의 원문 직접 후보 대신, run에 고정된 Wiki snapshot에서 권한·적용 시점을
통과한 page 5개를 같은 질의 벡터로 고르고 그 원문 링크를 펼친다. 펼친 passage는 raw와 같은 필터를 다시
거쳐 같은 원문 거리로 정렬해 20개까지 쓴다. 1·2·4·5·6·7은 A와 같다. Wiki 미준비·stale·후보 0개는
운영이면 raw로 fallback(effective_strategy=raw와 이유 기록), 엄격 평가면 실패로 기록하고 빈 결과를 낸다.
"""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Literal

from agent.modules.knowledge.contracts import APPLICATION_BASIS, Passage
from agent.modules.knowledge.service import KnowledgeService
from agent.modules.wiki.contracts import CandidateResult
from agent.modules.wiki.service import WikiService
from agent.shared.actor import ActorContext
from agent.shared.clock import KST
from agent.shared.errors import AppError, ErrorCode

DATE_BASES = frozenset(
    {
        "current",
        "explicit_date",
        "training_start",
        "trip_start",
        "approval_date",
        "request_date",
        "work_date",
        "processing_date",
    }
)
EVENT_BASES = DATE_BASES - {"current", "explicit_date"}
HORIZON_DAYS = 90
RETRIEVER_CONFIG_ID = "raw-exact-cosine-v1"
WIKI_RETRIEVER_CONFIG_ID = "wiki-exact-cosine-v1"  # Wiki 후보 5 → 링크 확장 → 공통 원문 거리 20
STRATEGIES = frozenset({"raw", "wiki_assisted", "full_context_reference"})
FULL_CONTEXT_CONFIG_ID = "full-context-reference-v1"  # 허용 원문 전체, 같은 원문 거리 순(D-22, docs/13)
FULL_CONTEXT_LIMIT = 100_000  # passage 수 상한(검색 SQL LIMIT). corpus 전체 1,545개보다 크다
RAW_CANDIDATE_LIMIT = 20
WIKI_CANDIDATE_LIMIT = 5
EXPANDED_PASSAGE_LIMIT = 20
# LookupApplicableBasis에서 볼 상위 판본 수. 가장 가까운 판본이 사건 기준 규범일 때만 날짜를 묻는다.
# 2026-10-18 실제 모델 smoke에서 3개로 두자 관련 없는 사건 기준 규정이 섞여 되묻기가 과했다(TS-24).
_BASIS_LOOKUP_TOP = 1


@dataclass(frozen=True)
class SearchRequest:
    query: str
    date_basis: str
    as_of_date: date | None = None
    event_key: str | None = None
    top_k: int = RAW_CANDIDATE_LIMIT
    # 사건 날짜 근원 검증 결과(MOD-02). 실패 사유가 있으면 되묻는다.
    date_problem: str | None = None
    date_evidence: dict[str, Any] = field(default_factory=dict)
    # 경과조항 조건용 다른 사건 날짜(MOD-02가 사용자 문장으로 검증한 값만). {date_basis: date}
    verified_events: dict[str, date] = field(default_factory=dict)
    # D-61: current 기준인데 사건 기준 규정이 걸리면, MOD-02가 사용자 문장으로 허용한 경우에만
    # 오늘을 사건 날짜로 본다.
    assume_today: bool = False


@dataclass(frozen=True)
class SupportGroup:
    group_id: str  # artifact_id:support_group
    rank: int
    distance: float
    passages: tuple[Passage, ...]

    @property
    def token_estimate(self) -> int:
        return sum(p.token_estimate for p in self.passages)


@dataclass(frozen=True)
class RetrievalResult:
    resolution: Literal["resolved", "needs_clarification", "unsupported"]
    knowledge_as_of: datetime
    corpus_snapshot_id: str
    date_basis: str
    as_of_date: date | None
    event_key: str | None
    prospective: bool = False
    groups: tuple[SupportGroup, ...] = ()
    clarification: dict[str, Any] | None = None
    unsupported: dict[str, Any] | None = None
    date_evidence: dict[str, Any] = field(default_factory=dict)
    # 적용 원규정 판본이 없는 날짜(05-retrieval-assembly). 안내로 금액·권리·의무를 확정하지 않는다.
    normative_gap: dict[str, Any] | None = None
    # 결과 문서의 명시 우선관계(대상 문서가 보이는 것만). {from_title, kind, to_title, quote}
    authority_relations: tuple[dict[str, Any], ...] = ()
    # 경과조항 조건의 사건 날짜가 빠졌을 때의 후속 되묻기 {reason, required_event_type, event_key, prompt}
    transition_pending: dict[str, Any] | None = None
    requested_strategy: str = "raw"
    effective_strategy: str = "raw"
    retriever_config_id: str = RETRIEVER_CONFIG_ID
    wiki_snapshot_id: str | None = None
    # 운영 B가 raw로 바꾼 이유(wiki_not_ready/wiki_stale/no_wiki_candidates).
    # 엄격 B는 같은 이유를 strict_failure에 남긴다.
    fallback_reason: str | None = None
    strict_failure: str | None = None
    # 진단용 Wiki 후보(page_id, 거리). 모델에 보내지 않는다(A/B 도구 결과 형식을 같게 둔다).
    wiki_candidates: tuple[tuple[str, float], ...] = ()

    def trace(self) -> dict[str, Any]:
        """도구 호출 기록용 검색 경로(모델에 보이지 않음)."""
        return {
            "resolution": self.resolution,
            "date_basis": self.date_basis,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "knowledge_as_of": self.knowledge_as_of.isoformat(),
            # 패킹 전 후보(Recall@pool): A는 원문 후보, B는 확장 원문 후보. 그룹 순서·대표 거리 포함.
            "pool": [
                {
                    "group_id": g.group_id,
                    "rank": g.rank,
                    "distance": g.distance,
                    "passage_ids": [p.passage_id for p in g.passages],
                }
                for g in self.groups
            ],
            "requested_strategy": self.requested_strategy,
            "effective_strategy": self.effective_strategy,
            "fallback_reason": self.fallback_reason,
            "strict_failure": self.strict_failure,
            "retriever_config_id": self.retriever_config_id,
            "corpus_snapshot_id": self.corpus_snapshot_id,
            "wiki_snapshot_id": self.wiki_snapshot_id,
            "wiki_candidates": [list(c) for c in self.wiki_candidates],
        }


class RetrievalService:
    def __init__(self, knowledge: KnowledgeService, wiki: WikiService | None = None) -> None:
        self._knowledge = knowledge
        self._wiki = wiki

    async def current_snapshot(self) -> str | None:
        return await self._knowledge.current_snapshot()

    async def current_wiki_snapshot(self) -> str | None:
        """run 수락 때 고정할 Wiki snapshot(B 대화만). 실행 도중 최신 Wiki로 바꾸지 않는다."""
        return await self._wiki.current_snapshot() if self._wiki is not None else None

    async def visible_document_keys(self, actor: ActorContext, keys: set[str]) -> set[str]:
        """CP-05 문서 쪽 재검증(MOD-01이 이력·최종 응답을 가릴 때)."""
        return await self._knowledge.visible_document_keys(actor, keys)

    async def search(
        self,
        actor: ActorContext,
        request: SearchRequest,
        *,
        knowledge_as_of: datetime,
        snapshot_id: str | None,
        strategy: str = "raw",
        wiki_snapshot_id: str | None = None,
        strict: bool = False,
    ) -> RetrievalResult:
        if snapshot_id is None:
            raise AppError(ErrorCode.RETRIEVAL_NOT_READY)
        if strategy not in STRATEGIES:
            raise AppError(ErrorCode.RETRIEVAL_NOT_READY)
        if strategy == "full_context_reference" and actor.source != "eval_fixture":
            # 평가 대조군은 평가 포트만 쓴다(CT-13). 운영 경로에서는 비활성이다.
            raise AppError(ErrorCode.RETRIEVAL_NOT_READY)
        if request.date_basis not in DATE_BASES:
            raise AppError(ErrorCode.TOOL_ARGUMENT_INVALID, details={"field_names": ["date_basis"]})
        today = knowledge_as_of.astimezone(KST).date()
        base = {
            "knowledge_as_of": knowledge_as_of,
            "corpus_snapshot_id": snapshot_id,
            "date_basis": request.date_basis,
            "event_key": request.event_key,
            "requested_strategy": strategy,
            "effective_strategy": strategy,
            "retriever_config_id": {
                "wiki_assisted": WIKI_RETRIEVER_CONFIG_ID,
                "full_context_reference": FULL_CONTEXT_CONFIG_ID,
            }.get(strategy, RETRIEVER_CONFIG_ID),
            "wiki_snapshot_id": wiki_snapshot_id if strategy == "wiki_assisted" else None,
        }
        if request.date_basis == "current":
            as_of = today
            evidence = {"source": "run_accepted_at"}
        elif (
            request.as_of_date is None
            and request.assume_today
            and request.date_problem in (None, "missing_date")
        ):
            # 사건 기준으로 물었지만 날짜를 말하지 않은 현재형 질문(D-61): 사건 날짜를 오늘로 본다.
            as_of = today
            evidence = {"source": "assumed_today", "event_basis": request.date_basis}
        elif request.as_of_date is None:
            reason = request.date_problem or "missing_date"
            return RetrievalResult(
                "needs_clarification",
                as_of_date=None,
                clarification=_clarify(reason, request.date_basis, request.event_key),
                **base,
            )
        else:
            as_of = request.as_of_date
            evidence = dict(request.date_evidence) or {"source": "server_argument"}
        if as_of > today + timedelta(days=HORIZON_DAYS):
            return RetrievalResult(
                "unsupported",
                as_of_date=None,
                unsupported={
                    "reason": "event_out_of_horizon",
                    "safe_message": f"오늘부터 {HORIZON_DAYS}일보다 먼 날짜의 규정은 안내하지 않습니다.",
                },
                **base,
            )
        vector = await self._knowledge.embed_query(request.query)

        hints = await self._knowledge.lookup_basis(
            actor, snapshot_id, vector, knowledge_as_of=knowledge_as_of
        )
        required = [
            h.application_basis
            for h in hints[:_BASIS_LOOKUP_TOP]
            if h.document_role == "normative" and h.application_basis in EVENT_BASES
        ]
        if required and request.date_basis == "current" and request.assume_today:
            # 날짜 없이 현재형으로 물었다(D-61). 사건 날짜를 오늘로 보고, 이후 필터·판본·공백 판정은
            # 그 사건 기준으로 한다(current 그대로 두면 사건 기준 규범 원문이 걸러진다).
            request = replace(request, date_basis=required[0], as_of_date=today)
            base = {**base, "date_basis": required[0]}
            evidence = {"source": "assumed_today", "event_basis": required[0]}
        elif required and request.date_basis in ("current", "explicit_date"):
            # 사건 기준 규정인데 사건 날짜가 없다. 제한 문서의 이름은 드러내지 않고 필요한 사건 종류만 묻는다.
            return RetrievalResult(
                "needs_clarification",
                as_of_date=None,
                clarification=_clarify("missing_date", required[0], request.event_key),
                **base,
            )

        # 규범 공백(T-17): 이 날짜 기준에 맞는 가장 가까운 규범을 판본 후보 전체에서 본다
        # (안내가 더 가까워도).
        normative = [h for h in hints if h.document_role == "normative"]
        target = next((h for h in normative if _basis_matches(h.application_basis, request.date_basis)), None)
        if target is None and request.date_basis in EVENT_BASES:
            other = next((h.application_basis for h in normative if h.application_basis in EVENT_BASES), None)
            if other is not None:
                # 다른 사건 기준의 규범만 있다. 모델이 날짜 기준을 잘못 골랐을 수 있으니
                # 안내로 답하지 않고 묻는다.
                return RetrievalResult(
                    "needs_clarification",
                    as_of_date=None,
                    clarification=_clarify("basis_mismatch", other, request.event_key),
                    **base,
                )
        normative_gap = None
        if target is not None and not await self._knowledge.normative_covers(
            actor, snapshot_id, target.document_key, as_of_date=as_of, knowledge_as_of=knowledge_as_of
        ):
            # 문서 키·제목은 내보내지 않는다(이 사용자에게 보이는 문서지만 결과에 필요 없는 값).
            normative_gap = {"reason": "normative_gap", "safe_message": _GAP_MESSAGE}

        limit = min(request.top_k, RAW_CANDIDATE_LIMIT)
        route: dict[str, Any] = {}
        hits: list[Passage] | None = None
        if strategy == "wiki_assisted":
            hits, route = await self._wiki_hits(
                actor, vector, snapshot_id, wiki_snapshot_id, as_of, knowledge_as_of, request, strict
            )
        if strategy == "full_context_reference":
            # 대조군: 검색 대신 이 사건 날짜에 허용된 passage 전체(필터는 A와 같다).
            everything = await self._knowledge.search(
                actor,
                snapshot_id,
                vector,
                knowledge_as_of=knowledge_as_of,
                as_of_date=as_of,
                limit=FULL_CONTEXT_LIMIT,
            )
            hits = [h for h in everything if _basis_fits(h, request.date_basis)]
        if hits is None:
            hits = await self._knowledge.search(
                actor,
                snapshot_id,
                vector,
                knowledge_as_of=knowledge_as_of,
                as_of_date=as_of,
                # 기준이 맞지 않는 규정이 후보 자리를 차지해 거짓 0건이 되지 않게, 넉넉히 받아 거른 뒤 자른다.
                limit=limit * 3,
            )
            hits = [h for h in hits if _basis_fits(h, request.date_basis)][:limit]
        base.update(route)
        if base.get("strict_failure"):
            # 엄격 B: Wiki 경로가 없으면 원문 직접 검색으로 바꾸지 않는다(평가에서 실패로 집계).
            return RetrievalResult(
                "resolved", as_of_date=as_of, prospective=as_of > today, date_evidence=evidence, **base
            )
        if strategy == "full_context_reference":
            groups = _whole_groups(hits)
        else:
            groups = await self._groups(actor, hits)
        events = dict(request.verified_events)
        if request.date_basis in EVENT_BASES:
            events[request.date_basis] = as_of
        groups, missing_event = await self._expand_transitions(
            actor, snapshot_id, groups, request.date_basis, events, knowledge_as_of
        )
        pending = _transition_prompt(missing_event, request.event_key) if missing_event else None
        relations = await self._authority_relations(actor, snapshot_id, groups, knowledge_as_of)
        return RetrievalResult(
            "resolved",
            as_of_date=as_of,
            prospective=as_of > today,
            groups=tuple(groups),
            date_evidence=evidence,
            normative_gap=normative_gap,
            authority_relations=relations,
            transition_pending=pending,
            **base,
        )

    async def _wiki_hits(
        self,
        actor: ActorContext,
        vector: tuple[float, ...],
        snapshot_id: str,
        wiki_snapshot_id: str | None,
        as_of: date,
        knowledge_as_of: datetime,
        request: SearchRequest,
        strict: bool,
    ) -> tuple[list[Passage] | None, dict[str, Any]]:
        """B: Wiki 후보 → 원문 링크 확장. None이면 raw로 진행(운영 fallback)한다."""
        if self._wiki is None:
            outcome = CandidateResult("not_ready", None)
        else:
            outcome = await self._wiki.get_candidates(
                actor,
                vector,
                corpus_snapshot_id=snapshot_id,
                wiki_snapshot_id=wiki_snapshot_id,
                as_of_date=as_of,
                knowledge_as_of=knowledge_as_of,
                limit=WIKI_CANDIDATE_LIMIT,
            )
        route: dict[str, Any] = {
            "wiki_candidates": tuple((c.page_id, round(c.distance, 6)) for c in outcome.candidates)
        }
        reason = {"not_ready": "wiki_not_ready", "stale": "wiki_stale"}.get(outcome.status)
        if reason is None and not outcome.candidates:
            reason = "no_wiki_candidates"
        if reason is not None:
            if strict:
                return [], {**route, "strict_failure": reason}
            return None, {
                **route,
                "effective_strategy": "raw",
                "fallback_reason": reason,
                "retriever_config_id": RETRIEVER_CONFIG_ID,  # 실제로 실행한 설정
            }
        limit = min(request.top_k, EXPANDED_PASSAGE_LIMIT)
        linked = await self._knowledge.passages_by_ids(
            actor,
            snapshot_id,
            {p for c in outcome.candidates for p in c.passage_ids},
            vector,
            knowledge_as_of=knowledge_as_of,
            as_of_date=as_of,
            limit=limit * 3,
        )
        return [h for h in linked if _basis_fits(h, request.date_basis)][:limit], route

    async def _expand_transitions(
        self,
        actor: ActorContext,
        snapshot_id: str,
        groups: list[SupportGroup],
        date_basis: str,
        events: dict[str, date],
        knowledge_as_of: datetime,
    ) -> tuple[list[SupportGroup], str | None]:
        """ExpandTransitionEvidence(05-retrieval-assembly). 자동 우선순위 추정은 하지 않는다."""
        meta = await self._knowledge.edition_relations({p.edition_id for g in groups for p in g.passages[:1]})
        out: list[SupportGroup] = []
        missing_event: str | None = None
        attached: set[tuple[str, str]] = set()  # (반대편 파일, 조항): 같은 조항은 결과 전체에서 한 번만
        for group in groups:
            base = group.passages[0]
            added: list[Passage] = []
            for relation in (meta.get(base.edition_id) or {}).get("transition_relations", []):
                if relation.get("application_basis") != date_basis:
                    continue
                conditions = relation.get("event_conditions") or []
                known = [c for c in conditions if c["event"] in events]
                if not all(_condition_holds(events[c["event"]], c) for c in known):
                    continue  # 이미 알려진 사건이 조건 밖이면 이 경과조항은 이 사건의 것이 아니다
                missing = [c["event"] for c in conditions if c["event"] not in events]
                if missing:
                    missing_event = missing_event or missing[0]
                    continue
                target = (relation["to_source_file_id"], relation["clause_anchor"])
                if target in attached:
                    continue
                attached.add(target)
                added.extend(
                    await self._knowledge.transition_passages(
                        actor,
                        snapshot_id,
                        relation["to_source_file_id"],
                        relation["clause_anchor"],
                        knowledge_as_of=knowledge_as_of,
                    )
                )
            if added:
                ids = {p.passage_id for p in group.passages}
                extra = tuple(
                    replace(p, extra={**p.extra, "source_role": "transition"}, distance=None, rank=None)
                    for p in added
                    if p.passage_id not in ids
                )
                group = replace(group, passages=group.passages + extra)
            out.append(group)
        return out, missing_event

    async def _authority_relations(
        self, actor: ActorContext, snapshot_id: str, groups: list[SupportGroup], knowledge_as_of: datetime
    ) -> tuple[dict[str, Any], ...]:
        bases = {g.passages[0].edition_id: g.passages[0] for g in groups}
        meta = await self._knowledge.edition_relations(set(bases))
        pairs = [
            (bases[edition_id], relation)
            for edition_id, info in meta.items()
            for relation in info.get("authority_relations", [])
        ]
        titles = await self._knowledge.relation_titles(
            actor, snapshot_id, {r["target_document_key"] for _, r in pairs}, knowledge_as_of=knowledge_as_of
        )
        out, seen = [], set()
        for passage, relation in pairs:
            key = (passage.document_key, relation["kind"], relation["target_document_key"])
            if relation["target_document_key"] not in titles or key in seen:
                continue  # 볼 수 없는 대상 문서는 존재·제목을 드러내지 않는다
            seen.add(key)
            out.append(
                {
                    "from_title": passage.title,
                    "kind": relation["kind"],
                    "to_title": titles[relation["target_document_key"]],
                    "quote": relation["quote"],
                }
            )
        return tuple(out)

    async def _groups(self, actor: ActorContext, hits: list[Passage]) -> list[SupportGroup]:
        groups: list[SupportGroup] = []
        seen: set[str] = set()
        for hit in hits:
            group_id = f"{hit.artifact_id}:{hit.support_group}"
            if group_id in seen:
                continue
            seen.add(group_id)
            members = await self._knowledge.support_group(actor, hit)
            if not members:
                continue
            groups.append(
                SupportGroup(group_id, hit.rank or len(groups) + 1, hit.distance or 0.0, tuple(members))
            )
        groups.sort(key=lambda g: (g.distance, g.passages[0].passage_id))
        return groups


def _whole_groups(hits: list[Passage]) -> list[SupportGroup]:
    """passage가 모두 있을 때 support_group을 다시 조회하지 않고 묶는다(그룹 거리 = 가장 가까운 passage)."""
    members: dict[str, list[Passage]] = {}
    for hit in hits:
        members.setdefault(f"{hit.artifact_id}:{hit.support_group}", []).append(hit)
    groups = []
    for group_id, passages in members.items():
        ordered = sorted(passages, key=lambda p: (p.extra.get("ordinal", 0), p.passage_id))
        distance = min(p.distance or 0.0 for p in passages)
        groups.append(SupportGroup(group_id, 0, distance, tuple(ordered)))
    groups.sort(key=lambda g: (g.distance, g.passages[0].passage_id))
    return [replace(g, rank=i) for i, g in enumerate(groups, start=1)]


def _transition_prompt(event_type: str, event_key: str | None) -> dict[str, Any]:
    name = _EVENT_NAMES.get(event_type, "기준 날짜")
    return {
        "reason": "missing_date",
        "required_event_type": event_type,
        "event_key": event_key,
        "prompt": f"경과조항 적용 여부를 확인하려면 {name}이 필요합니다. 날짜를 알려 주시겠어요?",
    }


def _condition_holds(event_date: date, condition: dict[str, Any]) -> bool:
    boundary = date.fromisoformat(condition["date"])
    return event_date < boundary if condition["compare"] == "before" else event_date >= boundary


def _basis_fits(passage: Passage, date_basis: str) -> bool:
    """규범의 적용 기준과 질문의 날짜 기준이 맞는가. 안내·일반 기준 규범은 날짜 기준과 무관하게 쓸 수 있다."""
    if passage.document_role != "normative":
        return True
    return _basis_fits_hint(passage.application_basis, date_basis)


def _basis_fits_hint(application_basis: str, date_basis: str) -> bool:
    if application_basis in ("general_reference", "per_claim"):
        return True
    return date_basis in APPLICATION_BASIS[application_basis]


def _basis_matches(application_basis: str, date_basis: str) -> bool:
    """공백 판정 대상: 대응표상 이 날짜 기준의 규범(per_claim은 부모만으로 날짜를 확정하지 않아 제외)."""
    return application_basis != "per_claim" and date_basis in APPLICATION_BASIS[application_basis]


_GAP_MESSAGE = (
    "그 날짜에 적용되는 규정 판본이 없어 금액·조건을 확정할 수 없습니다. "
    "안내 문서는 절차 확인용으로만 참고해 주세요."
)


_EVENT_NAMES = {
    "training_start": "교육 시작일",
    "trip_start": "출장 시작일",
    "approval_date": "최종 결재일",
    "request_date": "신청일(상신일)",
    "work_date": "근무일",
    "processing_date": "처리일",
    "explicit_date": "기준 날짜",
}


def _clarify(reason: str, event_type: str, event_key: str | None) -> dict[str, Any]:
    name = _EVENT_NAMES.get(event_type, "기준 날짜")
    prompt = (
        f"{name}이 올해인지 다른 해인지 알 수 없습니다. 연도를 포함한 날짜를 알려 주시겠어요?"
        if reason == "ambiguous_date"
        else f"적용할 규정 판본을 정하려면 {name}이 필요합니다. 날짜를 알려 주시겠어요?"
    )
    return {"reason": reason, "required_event_type": event_type, "event_key": event_key, "prompt": prompt}
