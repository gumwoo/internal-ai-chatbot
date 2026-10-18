"""MOD-11 raw 전략: SearchRequest(CT-13) → RetrievalResult(CT-14).

순서(docs/contracts/02-business-dates.md, 05-retrieval-assembly.md)
1. 날짜 검증: date_basis 닫힌 값, 사건 기준이면 as_of_date 필수(없으면 되묻기), 미래 90일 초과는 미지원.
2. LookupApplicableBasis: 날짜 필터 없이 관련 판본의 검수 메타데이터만 본다. 가장 가까운 규범이 사건 기준
   (교육 시작일 등)을 요구하는데 질문에 그 날짜가 없으면 되묻는다. 오늘 날짜로 금액부터 검색하지 않는다.
3. 검색: MOD-05가 권한·게시·지식 시점·규범 적용 구간으로 먼저 거른 후보만 받는다(raw_candidate_limit=20).
4. 조립: 후보마다 support_group(조항·FAQ 문항·표 전체)을 붙이고, 그룹을 대표 후보의 거리 순으로 정렬한다.
   같은 그룹은 한 번만 넣는다. 여러 검색의 최종 예산 조립은 MOD-02가 한다.
5. 규범 공백(T-17): 가장 가까운 규범이 이 날짜 기준에 맞는데 그 날짜를 포함하는 공개 판본이 없으면
   normative_gap을 표시한다. 안내 문서는 절차 확인용으로만 남기고, 결론 보류는 MOD-02가 한다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from agent.modules.knowledge.contracts import APPLICATION_BASIS, Passage
from agent.modules.knowledge.service import KnowledgeService
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
RAW_CANDIDATE_LIMIT = 20
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
    requested_strategy: str = "raw"
    effective_strategy: str = "raw"
    retriever_config_id: str = RETRIEVER_CONFIG_ID


class RetrievalService:
    def __init__(self, knowledge: KnowledgeService) -> None:
        self._knowledge = knowledge

    async def current_snapshot(self) -> str | None:
        return await self._knowledge.current_snapshot()

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
    ) -> RetrievalResult:
        if snapshot_id is None:
            raise AppError(ErrorCode.RETRIEVAL_NOT_READY)
        if request.date_basis not in DATE_BASES:
            raise AppError(ErrorCode.TOOL_ARGUMENT_INVALID, details={"field_names": ["date_basis"]})
        today = knowledge_as_of.astimezone(KST).date()
        base = {
            "knowledge_as_of": knowledge_as_of,
            "corpus_snapshot_id": snapshot_id,
            "date_basis": request.date_basis,
            "event_key": request.event_key,
        }
        if request.date_basis == "current":
            as_of = today
            evidence = {"source": "run_accepted_at"}
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
        if required and request.date_basis in ("current", "explicit_date"):
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

        hits = await self._knowledge.search(
            actor,
            snapshot_id,
            vector,
            knowledge_as_of=knowledge_as_of,
            as_of_date=as_of,
            # 기준이 맞지 않는 규정이 후보 자리를 차지해 거짓 0건이 되지 않게, 넉넉히 받아 거른 뒤 자른다.
            limit=min(request.top_k, RAW_CANDIDATE_LIMIT) * 3,
        )
        hits = [h for h in hits if _basis_fits(h, request.date_basis)][
            : min(request.top_k, RAW_CANDIDATE_LIMIT)
        ]
        groups = await self._groups(actor, hits)
        return RetrievalResult(
            "resolved",
            as_of_date=as_of,
            prospective=as_of > today,
            groups=tuple(groups),
            date_evidence=evidence,
            normative_gap=normative_gap,
            **base,
        )

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
    "request_date": "신청일",
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
