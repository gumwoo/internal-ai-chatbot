"""MOD-05 공개 작업: PublishCorpus, CurrentSnapshot, SearchPassages(권한·게시·시점 선필터),
LookupApplicableBasis, SupportGroup, GetEvidence, OpenSourcePdf, VisibleDocumentKeys, SetAcl.

권한은 두 겹이다.
1. SQL 선필터: 현재 resource_acl로 허용되지 않는 문서는 후보에도 들어오지 않는다(결과 수·제목도 새지 않는다).
2. 결과마다 MOD-09 정책 판정(evaluate)으로 다시 확인한다. 정책 형식이 틀리거나 모르는 값이 있으면 거부다.
게시: 준비한 판본을 한 트랜잭션에서 등록하고 snapshot 포인터를 바꾼다. 실패하면 이전 게시본이 그대로 남는다.
"""

import asyncio
import hashlib
import json
import uuid
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from agent.modules.identity_access.policy import ResourcePolicy, evaluate
from agent.modules.knowledge.contracts import (
    APPLICATION_BASIS,
    BasisHint,
    EditionMetadata,
    Passage,
    PreparedCorpus,
    PreparedEdition,
    PublishResult,
    SourceEdition,
)
from agent.modules.knowledge.tables import (
    EMBEDDING_DIM,
    acl_audit,
    chunk_embeddings,
    chunks,
    corpus_pointer,
    corpus_snapshots,
    document_editions,
    document_pages,
    logical_documents,
    parsed_artifacts,
    resource_acl,
    snapshot_members,
    source_files,
)
from agent.modules.model_integration.gemini_embedding import format_input
from agent.modules.model_integration.ports import EmbeddingConfig, EmbeddingModel
from agent.shared.actor import ActorContext
from agent.shared.clock import KST, Clock
from agent.shared.errors import AppError, ErrorCode
from agent.shared.tokens import estimate_tokens

POINTER = "current"
_NAMESPACE = uuid.UUID("6f1d8a52-3b0e-4f4e-9d39-0c2a3d5b7e11")


class PublishRejected(Exception):
    """게시 전 검사 실패. 이유 목록을 담는다. 이전 게시본은 바뀌지 않는다."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons[:5]))
        self.reasons = reasons


class KnowledgeService:
    def __init__(
        self,
        engine: AsyncEngine,
        clock: Clock,
        embedder: EmbeddingModel | None = None,
        *,
        embedding_model: str = "gemini-embedding-2",
        embedding_format: str = "gemini-embedding-2-prefix-v1",
        input_root: Path | None = None,
        embed_timeout_s: float = 10.0,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._embedding_format = embedding_format
        self._input_root = input_root
        self._embed_timeout_s = embed_timeout_s

    # --- 게시 ---

    async def publish(self, operator: ActorContext, corpus: PreparedCorpus) -> PublishResult:
        if operator.source != "operator_cli" or not _allowed(operator, "ops.corpus_publish"):
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        problems = validate_corpus(corpus)
        if problems:
            raise PublishRejected(problems)
        now = self._clock.now()
        snapshot_id = uuid.uuid4()
        try:
            return await self._publish(operator, corpus, snapshot_id, now)
        except IntegrityError as exc:
            # 같은 내용(hash)의 파일이 다른 ID로 들어오는 등 저장 제약 위반. 이전 게시본은 그대로다.
            raise PublishRejected([f"저장 제약 위반({type(exc.orig).__name__})"]) from exc

    async def _publish(
        self, operator: ActorContext, corpus: PreparedCorpus, snapshot_id: uuid.UUID, now: datetime
    ) -> PublishResult:
        async with self._engine.begin() as conn:
            artifact_ids = [await self._register(conn, edition, now) for edition in corpus.editions]
            await conn.execute(
                corpus_snapshots.insert().values(
                    snapshot_id=snapshot_id,
                    label=corpus.label,
                    scope=corpus.scope,
                    manifest_hash=corpus.manifest_hash,
                    config_hash=corpus.config_hash,
                    member_count=len(artifact_ids),
                    created_by=operator.user_id,
                    created_at=now,
                )
            )
            for artifact_id in artifact_ids:
                await conn.execute(
                    snapshot_members.insert().values(snapshot_id=snapshot_id, artifact_id=artifact_id)
                )
            revision = await conn.scalar(
                insert(corpus_pointer)
                .values(name=POINTER, snapshot_id=snapshot_id, revision=1, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["name"],
                    set_={
                        "snapshot_id": snapshot_id,
                        "revision": corpus_pointer.c.revision + 1,
                        "updated_at": now,
                    },
                )
                .returning(corpus_pointer.c.revision)
            )
        return PublishResult(str(snapshot_id), len(artifact_ids), int(revision))

    async def _register(self, conn: AsyncConnection, edition: PreparedEdition, now: datetime) -> uuid.UUID:
        meta = edition.metadata
        await conn.execute(
            insert(logical_documents)
            .values(
                document_key=meta.document_key,
                title=meta.title,
                domain=meta.domain,
                owning_department=meta.owning_department,
                created_at=now,
            )
            .on_conflict_do_nothing()
        )
        acl = (
            await conn.execute(select(resource_acl).where(resource_acl.c.document_key == meta.document_key))
        ).first()
        if acl is not None and acl.policy != meta.access_policy:
            # manifest로 권한을 바꾸지 않는다. 바꾸려면 감사가 남는 set_acl을 쓴다(조용히 무시하지 않음).
            raise PublishRejected(
                [f"{meta.source_file_id}: 저장된 ACL과 manifest의 access_policy가 다름(set_acl 사용)"]
            )
        if acl is None:
            await conn.execute(
                resource_acl.insert().values(
                    document_key=meta.document_key,
                    policy=meta.access_policy,
                    revision=1,
                    source=meta.access_policy_source,
                    updated_at=now,
                )
            )
        existing = (
            await conn.execute(
                select(source_files).where(source_files.c.source_file_id == meta.source_file_id)
            )
        ).first()
        if existing is not None and existing.sha256 != edition.sha256:
            raise PublishRejected(
                [f"{meta.source_file_id}: 같은 파일 ID의 원본 hash가 바뀜(새 판본으로 등록해야 함)"]
            )
        if existing is None:
            await conn.execute(
                source_files.insert().values(
                    source_file_id=meta.source_file_id,
                    filename=meta.filename,
                    sha256=edition.sha256,
                    page_count=edition.page_count,
                    registered_at=now,
                )
            )
        edition_id = await conn.scalar(
            select(document_editions.c.edition_id).where(
                document_editions.c.source_file_id == meta.source_file_id
            )
        )
        values = _edition_values(edition)
        if edition_id is None:
            edition_id = uuid.uuid4()
            await conn.execute(
                document_editions.insert().values(edition_id=edition_id, registered_at=now, **values)
            )
        else:
            # 게시된 판본은 불변이다. 메타데이터를 바꾸면 과거 snapshot의 결과·권한이 바뀌므로 거절한다
            # (불변 corpus snapshot, docs/corpus/01-metadata-contract.md).
            # 수정 판본 등록은 아직 지원하지 않는다.
            stored = (
                (
                    await conn.execute(
                        select(document_editions).where(document_editions.c.edition_id == edition_id)
                    )
                )
                .mappings()
                .one()
            )
            changed = sorted(k for k, v in values.items() if _normalized(stored[k]) != _normalized(v))
            if changed:
                raise PublishRejected(
                    [f"{meta.source_file_id}: 게시된 판본의 메타데이터는 바꿀 수 없음({changed})"]
                )
        artifact_id = await conn.scalar(
            select(parsed_artifacts.c.artifact_id).where(
                parsed_artifacts.c.edition_id == edition_id,
                parsed_artifacts.c.artifact_revision == edition.artifact_revision,
            )
        )
        if artifact_id is not None:
            return artifact_id
        artifact_id = uuid.uuid4()
        await conn.execute(
            parsed_artifacts.insert().values(
                artifact_id=artifact_id,
                edition_id=edition_id,
                artifact_revision=edition.artifact_revision,
                parser_revision=edition.parser_revision,
                chunk_config=edition.chunk_config,
                embedding_model=edition.embedding_model,
                embedding_dim=edition.embedding_dim,
                embedding_format=edition.embedding_format,
                quality=edition.quality,
                created_at=now,
            )
        )
        await conn.execute(
            document_pages.insert(), [{"artifact_id": artifact_id, **page} for page in edition.pages]
        )
        chunk_rows, vector_rows = [], []
        for chunk in edition.chunks:
            passage_id = uuid.uuid5(
                _NAMESPACE, f"{edition.sha256}|{edition.artifact_revision}|{chunk.ordinal}"
            )
            chunk_rows.append(
                {
                    "passage_id": passage_id,
                    "artifact_id": artifact_id,
                    "ordinal": chunk.ordinal,
                    "support_group": chunk.support_group,
                    "kind": chunk.kind,
                    "heading": chunk.heading,
                    "section_path": list(chunk.section_path),
                    "text": chunk.text,
                    "spans": list(chunk.spans),
                    "token_estimate": estimate_tokens(chunk.text),
                }
            )
            vector_rows.append({"passage_id": passage_id, "embedding": chunk.vector})
        if chunk_rows:
            # 여러 행을 한 번에 보낸다(executemany). 같은 트랜잭션이라 원자성은 그대로다.
            await conn.execute(chunks.insert(), chunk_rows)
            await conn.execute(chunk_embeddings.insert(), vector_rows)
        return artifact_id

    async def current_snapshot(self) -> str | None:
        async with self._engine.connect() as conn:
            value = await conn.scalar(
                select(corpus_pointer.c.snapshot_id).where(corpus_pointer.c.name == POINTER)
            )
        return str(value) if value else None

    # --- 검색 ---

    async def embed_query(self, query: str) -> tuple[float, ...]:
        if self._embedder is None:
            raise AppError(ErrorCode.RETRIEVAL_NOT_READY)
        config = EmbeddingConfig(self._embedding_model, EMBEDDING_DIM, "query")
        batch = await self._embedder.embed_once(
            (format_input(query, "query"),), config, self._embed_timeout_s
        )
        return batch.vectors[0]

    async def search(
        self,
        actor: ActorContext,
        snapshot_id: str,
        query_vector: tuple[float, ...],
        *,
        knowledge_as_of: datetime,
        as_of_date: date | None,
        limit: int,
        date_filter: bool = True,
    ) -> list[Passage]:
        """SearchPassages. 권한·게시(snapshot)·지식 시점·규범 적용 구간을 SQL에서 먼저 거른다.

        date_filter=False는 LookupApplicableBasis용(사건 날짜 필터 없이 지식 시점·권한만)이다.
        """
        if not _allowed(actor, "knowledge.search"):
            return []
        sql = _SEARCH_SQL.format(date_clause=_DATE_CLAUSE if date_filter else "")
        params = {
            **_acl_params(actor),
            "snapshot_id": uuid.UUID(snapshot_id),
            "query": _vector_literal(query_vector),
            "knowledge_as_of": knowledge_as_of,
            "as_of_date": as_of_date,
            "limit": limit,
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()
        passages = []
        for row in rows:
            if _row_allowed(actor, row["policy"]):
                # 순위는 허용된 결과 안에서만 매긴다(숨긴 결과의 존재·개수가 순위 공백으로 새지 않게).
                passage = _passage(row, snapshot_id)
                passages.append(replace(passage, distance=float(row["distance"]), rank=len(passages) + 1))
        return passages

    async def lookup_basis(
        self,
        actor: ActorContext,
        snapshot_id: str,
        query_vector: tuple[float, ...],
        *,
        knowledge_as_of: datetime,
    ) -> list[BasisHint]:
        """LookupApplicableBasis: 날짜 필터 없이 관련 판본의 검수 메타데이터만(답변용 passage 아님)."""
        hits = await self.search(
            actor,
            snapshot_id,
            query_vector,
            knowledge_as_of=knowledge_as_of,
            as_of_date=None,
            limit=10,
            date_filter=False,
        )
        seen: dict[str, BasisHint] = {}
        for hit in hits:
            seen.setdefault(
                hit.document_key, BasisHint(hit.document_key, hit.document_role, hit.application_basis)
            )
        return list(seen.values())

    async def normative_covers(
        self,
        actor: ActorContext,
        snapshot_id: str,
        document_key: str,
        *,
        as_of_date: date,
        knowledge_as_of: datetime,
    ) -> bool:
        """이 문서 키에 사건 날짜를 적용 구간에 포함하는 공개·게시 규범 판본이 있는가(규범 공백 확인).

        05-retrieval-assembly: 적용 원규정 판본에 공백이 있으면 안내로 결론을 대신하지 않는다.
        """
        if not _allowed(actor, "knowledge.search"):
            return False
        params = {
            **_acl_params(actor),
            "snapshot_id": uuid.UUID(snapshot_id),
            "document_key": document_key,
            "as_of_date": as_of_date,
            "knowledge_as_of": knowledge_as_of,
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(_COVERS_SQL), params)).mappings().all()
        return any(_row_allowed(actor, row["policy"]) for row in rows)

    async def edition_relations(self, edition_ids: set[str]) -> dict[str, dict[str, Any]]:
        """판본의 검수된 관계(transition_relations·authority_relations).

        이미 허용된 passage의 판본만 묻는다.
        """
        if not edition_ids:
            return {}
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        document_editions.c.edition_id,
                        document_editions.c.source_file_id,
                        document_editions.c.transition_relations,
                        document_editions.c.authority_relations,
                    ).where(document_editions.c.edition_id.in_([uuid.UUID(e) for e in edition_ids]))
                )
            ).all()
        return {
            str(row.edition_id): {
                "source_file_id": row.source_file_id,
                "transition_relations": list(row.transition_relations or []),
                "authority_relations": list(row.authority_relations or []),
            }
            for row in rows
        }

    async def transition_passages(
        self,
        actor: ActorContext,
        snapshot_id: str,
        source_file_id: str,
        clause_anchor: str,
        *,
        knowledge_as_of: datetime,
    ) -> list[Passage]:
        """ExpandTransitionEvidence의 원문 회수: 반대편 판본에서 조항 제목이 clause_anchor인 단위 전체.

        사건 조건 판정은 MOD-11이 한다. 여기서는 게시·공개 시각·철회·현재 ACL만 본다(날짜 필터 없음).
        """
        if not _allowed(actor, "knowledge.search"):
            return []
        params = {
            **_acl_params(actor),
            "snapshot_id": uuid.UUID(snapshot_id),
            "source_file_id": source_file_id,
            "anchor": clause_anchor,
            "knowledge_as_of": knowledge_as_of,
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(_TRANSITION_SQL), params)).mappings().all()
        return [_passage(row, snapshot_id) for row in rows if _row_allowed(actor, row["policy"])]

    async def relation_titles(
        self, actor: ActorContext, snapshot_id: str, keys: set[str], *, knowledge_as_of: datetime
    ) -> dict[str, str]:
        """우선관계 대상 문서 중 지금 이 actor가 볼 수 있는 것의 현행 제목(볼 수 없는 문서는 빠진다)."""
        visible = await self.visible_document_keys(actor, keys)
        if not visible:
            return {}
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(_TITLE_SQL),
                    {
                        "snapshot_id": uuid.UUID(snapshot_id),
                        "keys": sorted(visible),
                        "knowledge_as_of": knowledge_as_of,
                    },
                )
            ).all()
        return {row.document_key: row.title for row in rows}

    async def support_group(self, actor: ActorContext, passage: Passage) -> list[Passage]:
        """같은 단위(조항·FAQ 문항·표)의 청크 전체. 권한은 문서 키 단위라 기준 passage와 같다."""
        sql = _GROUP_SQL
        params = {
            **_acl_params(actor),
            "artifact_id": uuid.UUID(passage.artifact_id),
            "support_group": passage.support_group,
            "snapshot_id": uuid.UUID(passage.corpus_snapshot_id),
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()
        return [
            _passage(row, passage.corpus_snapshot_id)
            for row in rows
            if _row_allowed(actor, row["policy"]) and _allowed(actor, "knowledge.search")
        ]

    # --- Wiki(MOD-10·11) 포트 ---

    async def read_build_sources(self, operator: ActorContext, snapshot_id: str) -> list[SourceEdition]:
        """ReadBuildSources: Wiki 빌드 운영자(ops.wiki_build, 운영 CLI)가 snapshot의 게시 판본 전체를 읽는다.

        철회 판본은 넣지 않는다. 권한은 판본마다 정책을 그대로 돌려주고(page 권한 등급 분할용) 거르지 않는다.
        """
        if operator.source != "operator_cli" or not _allowed(operator, "ops.wiki_build"):
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(text(_BUILD_SOURCES_SQL), {"snapshot_id": uuid.UUID(snapshot_id)}))
                .mappings()
                .all()
            )
        editions: dict[str, list[Any]] = {}
        for row in rows:
            editions.setdefault(str(row["edition_id"]), []).append(row)
        out = []
        for edition_id, members in editions.items():
            first = members[0]
            out.append(
                SourceEdition(
                    edition_id=edition_id,
                    document_key=first["document_key"],
                    source_file_id=first["source_file_id"],
                    title=first["title"],
                    version=first["version"],
                    document_role=first["document_role"],
                    application_basis=first["application_basis"],
                    edition_state=first["edition_state"],
                    available_from=first["available_from"],
                    effective_from=first["effective_from"],
                    effective_to=first["effective_to"],
                    guidance_valid_from=first["guidance_valid_from"],
                    guidance_valid_to=first["guidance_valid_to"],
                    access_policy=dict(first["policy"]),
                    passages=tuple(_passage(row, snapshot_id) for row in members),
                )
            )
        return sorted(out, key=lambda e: (e.document_key, e.effective_from or date.min, e.edition_id))

    async def visible_editions(
        self, actor: ActorContext, snapshot_id: str, edition_ids: set[str], *, knowledge_as_of: datetime
    ) -> set[str]:
        """현재 접근 판정(CT-15 교집합 검사용): 이 actor가 지금 읽을 수 있는 snapshot 판본 ID.

        현재 ACL·철회·지식 시점(공개 전 판본 제외)을 본다. Wiki page는 기여 판본이 모두 여기 있어야 보인다.
        """
        if not edition_ids or not _allowed(actor, "knowledge.search"):
            return set()
        try:
            keys = [uuid.UUID(e) for e in edition_ids]
        except ValueError:
            return set()
        params = {
            **_acl_params(actor),
            "snapshot_id": uuid.UUID(snapshot_id),
            "edition_ids": keys,
            "knowledge_as_of": knowledge_as_of,
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(_VISIBLE_EDITIONS_SQL), params)).mappings().all()
        return {str(row["edition_id"]) for row in rows if _row_allowed(actor, row["policy"])}

    async def passages_by_ids(
        self,
        actor: ActorContext,
        snapshot_id: str,
        passage_ids: set[str],
        query_vector: tuple[float, ...],
        *,
        knowledge_as_of: datetime,
        as_of_date: date | None,
        limit: int,
    ) -> list[Passage]:
        """Wiki 링크 확장(B): 링크된 passage 중 raw 검색과 같은 필터(권한·게시·지식 시점·규범 적용 구간)를
        통과한 것만 같은 원문 거리로 정렬해 돌려준다. Wiki 거리는 쓰지 않는다(공통 원문 거리 정렬, docs/13).
        """
        if not passage_ids or not _allowed(actor, "knowledge.search"):
            return []
        try:
            keys = [uuid.UUID(p) for p in passage_ids]
        except ValueError:
            return []
        params = {
            **_acl_params(actor),
            "snapshot_id": uuid.UUID(snapshot_id),
            "query": _vector_literal(query_vector),
            "knowledge_as_of": knowledge_as_of,
            "as_of_date": as_of_date,
            "limit": limit,
            "passage_ids": keys,
        }
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(_LINKED_SQL), params)).mappings().all()
        passages = []
        for row in rows:
            if _row_allowed(actor, row["policy"]):
                passage = _passage(row, snapshot_id)
                passages.append(replace(passage, distance=float(row["distance"]), rank=len(passages) + 1))
        return passages

    # --- 근거·PDF ---

    async def get_evidence(self, actor: ActorContext, passage_id: str) -> Passage:
        """GetEvidence: 현재 ACL·철회 상태를 다시 확인한다. 미존재와 접근 불가는 같은 404다."""
        try:
            key = uuid.UUID(passage_id)
        except ValueError as exc:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND) from exc
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(_EVIDENCE_SQL),
                        {**_acl_params(actor), "passage_id": key, "now": self._clock.now()},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or not _allowed(actor, "knowledge.search") or not _row_allowed(actor, row["policy"]):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
        return _passage(row, None)

    async def open_source_pdf(self, actor: ActorContext, source_file_id: str) -> Path:
        """OpenSourcePdf: 현재 ACL·철회 확인 후 입력 루트 안의 원본 경로. 미존재·불허·철회는 같은 404."""
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(text(_PDF_SQL), {**_acl_params(actor), "source_file_id": source_file_id}))
                .mappings()
                .first()
            )
        if (
            row is None
            or self._input_root is None
            or not _allowed(actor, "knowledge.search")
            or not _row_allowed(actor, row["policy"])
        ):
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
        root = self._input_root.resolve()
        path = (root / row["filename"]).resolve()
        if root not in path.parents or path.suffix.lower() != ".pdf" or not path.is_file():
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
        # 등록된 원본과 같은 파일인지 hash로 확인한다(파일명이 다른 PDF를 가리켜 다른 문서가 나가지 않게).
        if await asyncio.to_thread(_sha256, path) != row["sha256"]:
            raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
        return path

    async def visible_document_keys(self, actor: ActorContext, keys: set[str]) -> set[str]:
        """CP-05: 지금 이 actor가 볼 수 있는 문서 키(이력·캐시·최종 응답의 재검증용)."""
        if not keys or not _allowed(actor, "knowledge.search"):
            return set()
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(resource_acl.c.document_key, resource_acl.c.policy).where(
                        resource_acl.c.document_key.in_(sorted(keys)),
                        # 모든 판본이 철회된 문서는 볼 수 없다(철회는 과거 답변에도 즉시 적용).
                        resource_acl.c.document_key.in_(
                            select(document_editions.c.document_key).where(
                                document_editions.c.edition_state != "withdrawn"
                            )
                        ),
                    )
                )
            ).all()
        return {row.document_key for row in rows if _row_allowed(actor, row.policy)}

    async def set_acl(self, operator: ActorContext, document_key: str, policy: dict[str, Any]) -> int:
        """SetAcl(운영 CLI): 정책 형식을 검사하고 revision을 올리며 감사 행을 남긴다."""
        if operator.source != "operator_cli" or not _allowed(operator, "ops.access_admin"):
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED)
        if ResourcePolicy.from_mapping(policy) is None:
            raise AppError(ErrorCode.INVALID_REQUEST)
        now = self._clock.now()
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(resource_acl).where(resource_acl.c.document_key == document_key).with_for_update()
                )
            ).first()
            if row is None:
                raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
            revision = row.revision + 1
            await conn.execute(
                update(resource_acl)
                .where(resource_acl.c.document_key == document_key)
                .values(
                    policy=policy, revision=revision, source=f"set_acl:{operator.user_id}", updated_at=now
                )
            )
            await conn.execute(
                acl_audit.insert().values(
                    document_key=document_key,
                    actor_id=operator.user_id,
                    before=row.policy,
                    after=policy,
                    revision=revision,
                    changed_at=now,
                )
            )
        return revision


def validate_corpus(corpus: PreparedCorpus) -> list[str]:
    """게시 전 검사(T-18의 저장 쪽 방어). 메타데이터 검사 + 파싱 품질·청크·벡터 검사."""
    problems: list[str] = []
    if corpus.scope not in ("pilot", "release"):
        problems.append(f"알 수 없는 scope: {corpus.scope}")
    problems += validate_metadata([edition.metadata for edition in corpus.editions])
    for edition in corpus.editions:
        label = edition.metadata.source_file_id
        if edition.embedding_dim != EMBEDDING_DIM:
            problems.append(f"{label}: 임베딩 차원 {edition.embedding_dim} != {EMBEDDING_DIM}")
        if not edition.chunks:
            problems.append(f"{label}: 청크 없음(빈 추출은 게시하지 않음)")
        if any(len(c.vector) != EMBEDDING_DIM for c in edition.chunks):
            problems.append(f"{label}: 벡터 차원 불일치")
        quality = edition.quality or {}
        # 빈 페이지·글리프 미해석·숫자 누락·span 오류가 있으면 정상 텍스트로 게시하지 않는다
        # (docs/06-rag-design).
        for key in ("empty_pages", "cid_pages"):
            if quality.get(key):
                problems.append(f"{label}: 파싱 품질 {key}={quality[key]}")
        for key in ("numbers_missing", "span_errors"):
            if quality.get(key):
                problems.append(f"{label}: 파싱 품질 {key}={quality[key]}")
    return problems


def validate_metadata(metas: list[EditionMetadata]) -> list[str]:
    """메타데이터만 보는 검사. 임베딩(무료 티어 한도) 전에 먼저 돌린다."""
    problems: list[str] = []
    seen_files, seen_versions = set(), set()
    windows: dict[str, list[tuple[date, date | None, str]]] = {}
    guidance: dict[str, list[EditionMetadata]] = {}
    policies: dict[str, dict[str, Any]] = {}
    for meta in metas:
        label = meta.source_file_id
        if meta.review_status != "reviewed":
            problems.append(f"{label}: 검수되지 않음(review_status={meta.review_status})")
        if label in seen_files:
            problems.append(f"{label}: 파일 ID 중복")
        seen_files.add(label)
        if (meta.document_key, meta.version) in seen_versions:
            problems.append(f"{label}: 문서 키·판본 중복")
        seen_versions.add((meta.document_key, meta.version))
        if meta.document_role not in ("normative", "guidance"):
            problems.append(f"{label}: document_role 값 오류")
        if meta.application_basis not in APPLICATION_BASIS:
            problems.append(f"{label}: application_basis 값 오류")
        if not meta.basis_evidence:
            problems.append(f"{label}: basis_evidence 없음")
        if ResourcePolicy.from_mapping(meta.access_policy) is None:
            problems.append(f"{label}: access_policy 형식 오류(기본 거부)")
        if meta.document_key in policies and policies[meta.document_key] != meta.access_policy:
            problems.append(f"{label}: 같은 문서 키의 판본끼리 access_policy가 다름")
        policies.setdefault(meta.document_key, meta.access_policy)
        if meta.edition_state not in ("current", "superseded", "withdrawn"):
            problems.append(f"{label}: edition_state 값 오류")
        if meta.document_role == "normative":
            if meta.effective_from is None:
                problems.append(f"{label}: 규범 판본에 effective_from 없음")
            elif meta.effective_to is not None and meta.effective_to <= meta.effective_from:
                problems.append(f"{label}: 적용 구간이 비어 있음")
            else:
                windows.setdefault(meta.document_key, []).append(
                    (meta.effective_from, meta.effective_to, label)
                )
        else:
            start, stop = meta.guidance_valid_from, meta.guidance_valid_to
            if start is not None and stop is not None and stop <= start:
                problems.append(f"{label}: 안내 판본 구간이 비어 있거나 역전됨")
            guidance.setdefault(meta.document_key, []).append(meta)
    for key, spans in windows.items():
        spans.sort(key=lambda s: s[0])
        for (_, end_a, file_a), (start_b, _, file_b) in zip(spans, spans[1:], strict=False):
            if end_a is None or end_a > start_b:
                problems.append(f"{key}: 규범 적용 구간 겹침({file_a}, {file_b})")
    for key, editions in guidance.items():
        if len(editions) < 2:
            continue
        # 안내 개정 계열(IT-045/046 등)은 판본 구간이 있어야 하고 겹치지 않아야 한다(05-retrieval-assembly).
        if any(e.guidance_valid_from is None and e.guidance_valid_to is None for e in editions):
            problems.append(f"{key}: 안내 개정 쌍인데 guidance_valid 구간이 없음(둘 다 회수됨)")
            continue
        ordered = sorted(editions, key=lambda e: e.guidance_valid_from or datetime.min.replace(tzinfo=KST))
        for a, b in zip(ordered, ordered[1:], strict=False):
            if a.guidance_valid_to is None or (
                b.guidance_valid_from and a.guidance_valid_to > b.guidance_valid_from
            ):
                problems.append(f"{key}: 안내 판본 구간 겹침({a.source_file_id}, {b.source_file_id})")
    return problems


def _edition_values(edition: PreparedEdition) -> dict[str, Any]:
    meta = edition.metadata
    return {
        "document_key": meta.document_key,
        "version": meta.version,
        "source_file_id": meta.source_file_id,
        "source_document_number": meta.source_document_number,
        "title": meta.title,
        "document_type": meta.document_type,
        "document_role": meta.document_role,
        "application_basis": meta.application_basis,
        "basis_evidence": list(meta.basis_evidence),
        "available_from": meta.available_from,
        "effective_from": meta.effective_from,
        "effective_to": meta.effective_to,
        "guidance_valid_from": meta.guidance_valid_from,
        "guidance_valid_to": meta.guidance_valid_to,
        "supersedes_source_file_id": meta.supersedes_source_file_id,
        "edition_state": meta.edition_state,
        "transition_relations": list(meta.transition_relations),
        "authority_relations": list(meta.authority_relations),
        "related_document_keys": list(meta.related_document_keys),
        "review_status": meta.review_status,
    }


def _allowed(actor: ActorContext, capability: str) -> bool:
    return capability in actor.capabilities


def _row_allowed(actor: ActorContext, raw_policy: Any) -> bool:
    policy = ResourcePolicy.from_mapping(
        raw_policy if isinstance(raw_policy, dict) else json.loads(raw_policy)
    )
    return evaluate(actor, "knowledge.search", policy).allowed


def _acl_params(actor: ActorContext) -> dict[str, Any]:
    return {
        "user_id": actor.user_id,
        "department_ids": list(actor.department_ids),
        "role_ids": list(actor.role_ids),
        "capabilities": sorted(actor.capabilities),
    }


def _vector_literal(vector: tuple[float, ...]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _passage(row: Any, snapshot_id: str | None) -> Passage:
    return Passage(
        passage_id=str(row["passage_id"]),
        document_key=row["document_key"],
        edition_id=str(row["edition_id"]),
        source_file_id=row["source_file_id"],
        artifact_id=str(row["artifact_id"]),
        corpus_snapshot_id=snapshot_id or "",
        title=row["title"],
        version=row["version"],
        document_type=row["document_type"],
        document_role=row["document_role"],
        application_basis=row["application_basis"],
        edition_state=row["edition_state"],
        available_from=row["available_from"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        support_group=row["support_group"],
        kind=row["kind"],
        heading=row["heading"],
        section_path=tuple(row["section_path"] or ()),
        text=row["text"],
        page_spans=tuple(row["spans"] or ()),
        token_estimate=row["token_estimate"],
        acl_revision=row["acl_revision"],
    )


# 현재 ACL SQL 선필터. MOD-09 evaluate와 같은 의미(합집합·required_capabilities 모두·모르는 audience 거부).
_ACL_CLAUSE = """
  AND (
    a.policy->>'audience' = 'authenticated'
    OR (
      a.policy->>'audience' = 'restricted'
      AND (
        COALESCE(a.policy->'allowed_user_ids', '[]'::jsonb) ? :user_id
        OR COALESCE(a.policy->'allowed_department_ids', '[]'::jsonb) ?| CAST(:department_ids AS text[])
        OR COALESCE(a.policy->'allowed_role_ids', '[]'::jsonb) ?| CAST(:role_ids AS text[])
      )
    )
  )
  AND NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(COALESCE(a.policy->'required_capabilities', '[]'::jsonb)) = 'array'
        THEN COALESCE(a.policy->'required_capabilities', '[]'::jsonb)
        ELSE '["__invalid_policy__"]'::jsonb END
    ) AS rc(c)
    WHERE rc.c <> ALL(CAST(:capabilities AS text[]))
  )
"""

_COLUMNS = """
  c.passage_id, c.artifact_id, c.support_group, c.kind, c.heading, c.section_path, c.text, c.spans,
  c.token_estimate, e.edition_id, e.document_key, e.source_file_id, e.title, e.version, e.document_type,
  e.document_role, e.application_basis, e.edition_state, e.available_from, e.effective_from, e.effective_to,
  a.policy, a.revision AS acl_revision
"""

# 규범은 사건 날짜가 적용 구간 안, 안내는 지식 시점에서 유효한 안내 판본(docs/contracts/02-business-dates.md).
_DATE_CLAUSE = """
  AND (
    (e.document_role = 'normative' AND CAST(:as_of_date AS date) IS NOT NULL
      AND e.effective_from <= CAST(:as_of_date AS date)
      AND (e.effective_to IS NULL OR CAST(:as_of_date AS date) < e.effective_to))
    OR (e.document_role = 'guidance'
      AND (e.guidance_valid_from IS NULL OR e.guidance_valid_from <= :knowledge_as_of)
      AND (e.guidance_valid_to IS NULL OR :knowledge_as_of < e.guidance_valid_to))
  )
"""

_SEARCH_SQL = (
    "SELECT"
    + _COLUMNS
    + """, ce.embedding <=> CAST(:query AS vector) AS distance
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
JOIN chunks c ON c.artifact_id = p.artifact_id
JOIN chunk_embeddings ce ON ce.passage_id = c.passage_id
WHERE m.snapshot_id = :snapshot_id
  AND e.edition_state <> 'withdrawn'
  AND e.available_from <= :knowledge_as_of
"""
    + _ACL_CLAUSE
    + "{date_clause}"
    + """
ORDER BY distance, c.passage_id
LIMIT :limit
"""
)

# 링크 확장: 검색 SQL과 같은 필터에 passage ID 목록 조건만 더한다.
_LINKED_SQL = _SEARCH_SQL.replace(
    "ORDER BY distance", "  AND c.passage_id = ANY(CAST(:passage_ids AS uuid[]))\nORDER BY distance"
).format(date_clause=_DATE_CLAUSE)

_BUILD_SOURCES_SQL = (
    "SELECT"  # noqa: S608 - 고정 SQL 조각만 잇는다
    + _COLUMNS
    + """, e.guidance_valid_from, e.guidance_valid_to
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
JOIN chunks c ON c.artifact_id = p.artifact_id
WHERE m.snapshot_id = :snapshot_id AND e.edition_state <> 'withdrawn'
ORDER BY e.document_key, e.edition_id, c.ordinal
"""
)

_VISIBLE_EDITIONS_SQL = (
    """
SELECT e.edition_id, a.policy
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
WHERE m.snapshot_id = :snapshot_id
  AND e.edition_id = ANY(CAST(:edition_ids AS uuid[]))
  AND e.edition_state <> 'withdrawn'
  AND e.available_from <= :knowledge_as_of
"""
    + _ACL_CLAUSE
)

_TRANSITION_SQL = (
    "SELECT"  # noqa: S608 - 고정 SQL 조각만 잇는다(사용자 값은 바인드 변수)
    + _COLUMNS
    + """
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
JOIN chunks c ON c.artifact_id = p.artifact_id
WHERE m.snapshot_id = :snapshot_id
  AND e.source_file_id = :source_file_id
  AND e.edition_state <> 'withdrawn'
  AND e.available_from <= :knowledge_as_of
  AND c.support_group IN (
    SELECT c2.support_group FROM chunks c2 WHERE c2.artifact_id = p.artifact_id AND c2.heading = :anchor
  )
"""
    + _ACL_CLAUSE
    + "ORDER BY c.ordinal"
)

_TITLE_SQL = """
SELECT DISTINCT ON (e.document_key) e.document_key, e.title
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
WHERE m.snapshot_id = :snapshot_id AND e.document_key = ANY(CAST(:keys AS text[]))
  AND e.edition_state <> 'withdrawn' AND e.available_from <= :knowledge_as_of
ORDER BY e.document_key, (e.edition_state = 'current') DESC, e.effective_from DESC NULLS LAST
"""

_COVERS_SQL = (
    """
SELECT a.policy
FROM snapshot_members m
JOIN parsed_artifacts p ON p.artifact_id = m.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
WHERE m.snapshot_id = :snapshot_id
  AND e.document_key = :document_key
  AND e.document_role = 'normative'
  AND e.edition_state <> 'withdrawn'
  AND e.available_from <= :knowledge_as_of
  AND e.effective_from <= CAST(:as_of_date AS date)
  AND (e.effective_to IS NULL OR CAST(:as_of_date AS date) < e.effective_to)
"""
    + _ACL_CLAUSE
)

_GROUP_SQL = (
    "SELECT"
    + _COLUMNS
    + """
FROM chunks c
JOIN parsed_artifacts p ON p.artifact_id = c.artifact_id
JOIN snapshot_members m ON m.artifact_id = p.artifact_id AND m.snapshot_id = :snapshot_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
WHERE c.artifact_id = :artifact_id AND c.support_group = :support_group AND e.edition_state <> 'withdrawn'
"""
    + _ACL_CLAUSE
    + "ORDER BY c.ordinal"
)

_EVIDENCE_SQL = (
    "SELECT"
    + _COLUMNS
    + """
FROM chunks c
JOIN parsed_artifacts p ON p.artifact_id = c.artifact_id
JOIN document_editions e ON e.edition_id = p.edition_id
JOIN resource_acl a ON a.document_key = e.document_key
WHERE c.passage_id = :passage_id AND e.edition_state <> 'withdrawn' AND e.available_from <= :now
"""
    + _ACL_CLAUSE
)

_PDF_SQL = (
    """
SELECT f.filename, f.sha256, a.policy
FROM source_files f
JOIN document_editions e ON e.source_file_id = f.source_file_id
JOIN resource_acl a ON a.document_key = e.document_key
WHERE f.source_file_id = :source_file_id AND e.edition_state <> 'withdrawn'
"""
    + _ACL_CLAUSE
)


def _normalized(value: Any) -> Any:
    """메타데이터 비교용: JSON 목록/튜플·시각 표현 차이를 없앤다."""
    if isinstance(value, tuple):
        return [_normalized(v) for v in value]
    if isinstance(value, list):
        return [_normalized(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(KST).isoformat()
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
