"""MOD-11 raw 전략: SearchRequest(CT-13) → RetrievalResult(CT-14).

순서(docs/contracts/02-business-dates.md, 05-retrieval-assembly.md)
1. 날짜 검증: date_basis 닫힌 값, 사건 기준이면 as_of_date 필수(없으면 되묻기), 미래 90일 초과는 미지원.
2. LookupApplicableBasis: 날짜 필터 없이 관련 판본의 검수 메타데이터만 본다. 가장 가까운 규범이 사건 기준
   (교육 시작일 등)을 요구하는데 질문에 그 날짜가 없으면 되묻는다. 오늘 날짜로 금액부터 검색하지 않는다.
3. 검색: MOD-05가 권한·게시·지식 시점·규범 적용 구간으로 먼저 거른 후보만 받는다(후보 40, D-72).
4. 조립: 후보마다 support_group(조항·FAQ 문항·표 전체)을 붙이고, 그룹을 대표 후보의 거리 순으로 정렬한다.
   raw는 그 뒤 문서마다 앞 4그룹을 먼저 두고 나머지를 뒤로 다시 놓는다(D-72 문서 다양성).
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

import json
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
# D-72: 후보 passage 40·문서 다양성 순서(앞자리는 문서당 4그룹). v1은 후보 20·거리 순이었다.
RETRIEVER_CONFIG_ID = "raw-diverse-cosine-v2"
WIKI_RETRIEVER_CONFIG_ID = "wiki-exact-cosine-v1"  # Wiki 후보 5 → 링크 확장 → 공통 원문 거리 20
STRATEGIES = frozenset({"raw", "wiki_assisted", "full_context_reference"})
FULL_CONTEXT_CONFIG_ID = "full-context-reference-v1"  # 허용 원문 전체, 같은 원문 거리 순(D-22, docs/13)
FULL_CONTEXT_LIMIT = 100_000  # passage 수 상한(검색 SQL LIMIT). corpus 전체 1,545개보다 크다
RAW_CANDIDATE_LIMIT = 40  # D-72: 20이면 예산 4000의 41%만 쓰고 두 번째 문서가 들어갈 자리가 없었다
DIVERSE_GROUPS_PER_DOCUMENT = 4  # D-72: 앞자리에서 한 문서가 차지할 수 있는 그룹 수
WIKI_CANDIDATE_LIMIT = 5
EXPANDED_PASSAGE_LIMIT = 20
# LookupApplicableBasis에서 볼 상위 판본 수. 가장 가까운 판본이 사건 기준 규범일 때만 날짜를 묻는다.
# 2026-10-18 실제 모델 smoke에서 3개로 두자 관련 없는 사건 기준 규정이 섞여 되묻기가 과했다(TS-24).
_BASIS_LOOKUP_TOP = 1
_SPLIT_EDITIONS = 3  # D-67: 판본별로 함께 줄 최근 판본 수 상한
_SPLIT_GROUPS_PER_EDITION = 2  # D-67: 판본마다 함께 줄 그 규범 문서의 상위 근거 그룹 수
_SPLIT_OTHER_GROUPS = 1  # D-67: 판본마다 함께 줄 다른 문서(안내·관련 규정)의 그룹 수
# D-67: 판본별로 답하는 날짜 문제. 날짜가 없거나 사건 역할 대조에 실패한 경우만(ambiguous_date는 묻는다)
_SPLIT_REASONS = frozenset({"missing_date", "basis_mismatch"})


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
    # D-67 내부용: 판본별 재검색에서 질의 임베딩을 다시 만들지 않게 넘기고,
    # 재검색이 다시 나뉘지 않게 표시한다.
    query_vector: tuple[float, ...] | None = None
    split_from: str | None = None


@dataclass(frozen=True)
class SupportGroup:
    group_id: str  # artifact_id:support_group
    rank: int
    distance: float
    passages: tuple[Passage, ...]
    # D-67: 판본별로 함께 준 결과에서 이 그룹을 찾은 사건 날짜(그 판본의 시행 구간 안). 아니면 None
    as_of_date: date | None = None

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
    # D-67: 사건 날짜를 확정하지 못해 판본별 원문을 함께 줬다. {event_type, reason, editions:[{version,
    # effective_from, effective_to, as_of_date}]}. 모델은 되묻지 않고 판본별로 조건을 나눠 답한다.
    edition_split: dict[str, Any] | None = None

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
            split = await self._edition_split(
                actor,
                request,
                request.date_basis,
                reason,
                knowledge_as_of,
                snapshot_id,
                strategy,
                wiki_snapshot_id,
                strict,
            )
            if split is not None:
                return split
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
        vector = request.query_vector or await self._knowledge.embed_query(request.query)

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
            # 사건 기준 규정인데 사건 날짜가 없다. D-67: 판본별 원문을 함께 주고, 그럴 수 없을 때만 묻는다.
            # 제한 문서의 이름은 드러내지 않고 필요한 사건 종류만 묻는다.
            split = await self._edition_split(
                actor,
                replace(request, query_vector=vector),
                required[0],
                "missing_date",
                knowledge_as_of,
                snapshot_id,
                strategy,
                wiki_snapshot_id,
                strict,
            )
            if split is not None:
                return split
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
            if base.get("effective_strategy") == "raw":
                # D-72: 한 문서가 앞자리를 다 차지하지 않게 한다(예산 안에 다른 문서가 들어가도록).
                # 운영 B가 원문 검색으로 넘어간 경우도 같다(그때도 retriever_config_id는 이 설정이다).
                groups = _diversify(groups, DIVERSE_GROUPS_PER_DOCUMENT)
        events = dict(request.verified_events)
        if request.date_basis in EVENT_BASES and request.split_from is None:
            # D-67 판본별 재검색의 날짜는 서버가 고른 판본 대표일이라 확인된 사건 날짜가 아니다.
            # 경과조항 조건에 넣지 않는다(그 사건 날짜는 transition_pending으로 묻는다).
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

    async def _edition_split(
        self,
        actor: ActorContext,
        request: SearchRequest,
        basis: str,
        reason: str,
        knowledge_as_of: datetime,
        snapshot_id: str,
        strategy: str,
        wiki_snapshot_id: str | None,
        strict: bool,
    ) -> RetrievalResult | None:
        """D-67: 사건 날짜를 확정하지 못하면 되묻는 대신, 관련 규범 문서의 판본마다 그 시행 구간 안의 날짜로
        다시 검색해 결과를 합친다(판본을 고르지 않으므로 틀린 날짜를 확정하지 않는다).
        판본이 하나면 그 판본으로 답한다. 판본을 정할 문서가 없거나 판본별 검색 중 하나라도
        해결되지 않으면 None(호출자가 되묻는다).
        """
        if request.split_from is not None or basis not in EVENT_BASES | {"explicit_date"}:
            return None
        if reason not in _SPLIT_REASONS:
            # 사용자가 날짜를 말했는데 연도·시제·범위가 모호하다(ambiguous_date). 그 날짜가 판본 구간이나
            # 90일 범위 밖일 수 있으므로 판본별로 답하지 않고 묻는다.
            return None
        today = knowledge_as_of.astimezone(KST).date()
        vector = request.query_vector or await self._knowledge.embed_query(request.query)
        hints = await self._knowledge.lookup_basis(
            actor, snapshot_id, vector, knowledge_as_of=knowledge_as_of
        )
        target = next(
            (
                h
                for h in hints
                if h.document_role == "normative" and _basis_matches(h.application_basis, basis)
            ),
            None,
        )
        if target is None:
            return None
        periods = await self._knowledge.normative_periods(
            actor, snapshot_id, target.document_key, knowledge_as_of=knowledge_as_of
        )
        horizon = today + timedelta(days=HORIZON_DAYS)
        if not any(start <= today and (end is None or today < end) for start, end, _ in periods):
            return None  # 오늘 사건에 적용할 판본이 없다(공백): 판본별로 답하지 않고 묻는다
        parts: list[tuple[date, dict[str, Any]]] = []
        for start, end, version in periods:
            if start > horizon:
                continue  # 90일보다 뒤에 시행될 판본은 안내하지 않는다
            # 지난 판본은 끝나기 전날, 현행은 오늘, 공개된 장래 판본은 시행일로 검색한다
            day = start if start > today else min(today, end - timedelta(days=1)) if end else today
            edition = {
                "version": version,
                "effective_from": start.isoformat(),
                "effective_to": end.isoformat() if end else None,
                "as_of_date": day.isoformat(),
            }
            parts.append((day, edition))
        parts = parts[-_SPLIT_EDITIONS:]
        results: list[RetrievalResult] = []
        for day, _ in parts:
            sub = replace(
                request,
                date_basis=basis,
                as_of_date=day,
                date_problem=None,
                assume_today=False,
                date_evidence={"source": "edition_split", "reason": reason},
                query_vector=vector,
                split_from=reason,
            )
            result = await self.search(
                actor,
                sub,
                knowledge_as_of=knowledge_as_of,
                snapshot_id=snapshot_id,
                strategy=strategy,
                wiki_snapshot_id=wiki_snapshot_id,
                strict=strict,
            )
            if result.resolution != "resolved":
                return None
            results.append(result)
        latest = results[-1]
        if len(results) == 1:
            # 판본이 하나다(오늘을 포함하고 90일 안에 다음 판본이 없다): 날짜와 관계없이 같은 원문이 적용된다.
            return replace(latest, date_evidence={"source": "single_edition", "reason": reason})
        # 판본마다 상위 그룹만 남긴다: 판본별 결과가 근거 예산을 다 써서, 같은 실행의 다른 검색(날짜가 확인된
        # 재검색 등) 원문이 들어갈 자리가 없어지지 않게 한다.
        tagged = [
            (group.rank, -order, replace(group, as_of_date=day))
            for order, ((day, _), result) in enumerate(zip(parts, results, strict=True))
            for group in (
                result.groups
                if strategy == "full_context_reference"  # 기준선은 허용 원문 전체(D-50)
                else _split_groups(result.groups, target.document_key)
            )
        ]
        seen: set[str] = set()
        groups: list[SupportGroup] = []
        for _, _, group in sorted(tagged, key=lambda t: (t[0], t[1])):  # 순위가 같으면 최신 판본 먼저
            if group.group_id not in seen:
                seen.add(group.group_id)
                groups.append(group)
        relations: dict[str, dict[str, Any]] = {}
        for result in results:
            for relation in result.authority_relations:
                relations.setdefault(json.dumps(relation, sort_keys=True, ensure_ascii=False), relation)
        gaps = [r.normative_gap for r in results]
        return replace(
            latest,
            groups=tuple(groups),
            prospective=False,
            date_evidence={"source": "edition_split", "reason": reason},
            normative_gap=gaps[0] if all(gaps) else None,
            authority_relations=tuple(relations.values()),
            transition_pending=next((r.transition_pending for r in results if r.transition_pending), None),
            edition_split={
                "event_type": basis,
                "reason": reason,
                "document_key": target.document_key,
                "editions": [e for _, e in parts],
            },
            # 인용 없는 답을 서버가 되묻기로 바꿀 때 쓴다(MOD-02). 모델 보기에서는 뺀다.
            clarification=_clarify(reason, basis, request.event_key),
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


def _diversify(groups: list[SupportGroup], per_document: int) -> list[SupportGroup]:
    """D-72: 거리 순 그룹에서 문서마다 앞의 per_document개를 먼저 두고, 나머지를 거리 순으로 뒤에 붙인다.

    순위(rank)는 새 순서로 다시 매긴다(판본별 결과 D-67의 섞기와 예산 순서가 이 순서를 따른다).
    """
    first: list[SupportGroup] = []
    rest: list[SupportGroup] = []
    taken: dict[str, int] = {}
    for group in groups:
        key = group.passages[0].document_key
        if taken.get(key, 0) < per_document:
            taken[key] = taken.get(key, 0) + 1
            first.append(group)
        else:
            rest.append(group)
    return [replace(g, rank=i) for i, g in enumerate([*first, *rest], start=1)]


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


def _split_groups(groups: tuple[SupportGroup, ...], document_key: str) -> list[SupportGroup]:
    """D-67: 판본별 결과에서 한 판본이 남길 그룹.

    판본을 가르는 그 규범 문서의 그룹을 먼저 남기고, 다른 문서는 조금만 남긴다.
    """
    own = [g for g in groups if any(p.document_key == document_key for p in g.passages)]
    other = [g for g in groups if g not in own]
    return own[:_SPLIT_GROUPS_PER_EDITION] + other[:_SPLIT_OTHER_GROUPS]


def _clarify(reason: str, event_type: str, event_key: str | None) -> dict[str, Any]:
    name = _EVENT_NAMES.get(event_type, "기준 날짜")
    prompt = (
        f"{name}이 올해인지 다른 해인지 알 수 없습니다. 연도를 포함한 날짜를 알려 주시겠어요?"
        if reason == "ambiguous_date"
        else f"적용할 규정 판본을 정하려면 {name}이 필요합니다. 날짜를 알려 주시겠어요?"
    )
    return {"reason": reason, "required_event_type": event_type, "event_key": event_key, "prompt": prompt}
