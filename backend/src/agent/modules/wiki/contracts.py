"""MOD-10 입력·출력 값(CT-15 WikiBuild / WikiSnapshot / WikiCandidate)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


@dataclass(frozen=True)
class Topic:
    """검수된 주제 계획 한 항목. 문서 키 묶음이며 원문 내용을 담지 않는다."""

    topic_key: str
    title: str
    document_keys: tuple[str, ...]


@dataclass(frozen=True)
class TopicPlan:
    version: int
    status: str  # needs_review | reviewed
    topics: tuple[Topic, ...]
    plan_hash: str


@dataclass(frozen=True)
class PagePlan:
    """주제 × 권한 등급 × 시행 구간 하나. 기여 판본의 passage를 모두 입력으로 쓴다."""

    topic: Topic
    acl_class: str
    segment_key: str
    valid_from: date | None
    valid_to: date | None
    knowledge_from: datetime
    knowledge_to: datetime | None
    edition_ids: tuple[str, ...]
    passages: tuple[Any, ...]  # knowledge Passage


@dataclass(frozen=True)
class LinkCheck:
    passage_id: str
    edition_id: str
    quote: str


@dataclass(frozen=True)
class CheckedClaim:
    kind: Literal["claim", "relation"]
    text: str
    links: tuple[LinkCheck, ...]


@dataclass(frozen=True)
class CheckedPage:
    """생성 결과를 원문과 대조한 결과. problems가 있으면 게시하지 않는다(명시된 미게시 항목)."""

    title: str
    summary: str
    claims: tuple[CheckedClaim, ...]
    problems: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class BuildReport:
    build_id: str
    status: str
    corpus_snapshot_id: str
    pages_planned: int
    pages_valid: int
    pages_excluded: int
    uncovered_document_keys: tuple[str, ...]
    excluded: tuple[dict[str, Any], ...]
    usage: dict[str, Any]


@dataclass(frozen=True)
class WikiCandidate:
    """권한·적용 시점 검사를 통과한 page. 최종 근거가 아니라 원문 확장의 출발점이다."""

    page_id: str
    title: str
    distance: float
    passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateResult:
    status: Literal["ready", "not_ready", "stale"]
    wiki_snapshot_id: str | None
    candidates: tuple[WikiCandidate, ...] = field(default_factory=tuple)
