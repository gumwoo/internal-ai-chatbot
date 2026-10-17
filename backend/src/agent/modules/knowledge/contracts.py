"""MOD-05 입력·출력 값. CT-09 PreparedEdition/PreparedCorpus(MOD-06→05)와 CT-08 EvidencePassage."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# application_basis 닫힌 값과 허용 date_basis(docs/contracts/05-retrieval-assembly.md 대응표).
APPLICATION_BASIS = {
    "general_reference": frozenset({"current", "explicit_date"}),
    "training_start": frozenset({"training_start"}),
    "trip_start": frozenset({"trip_start"}),
    "approval_date": frozenset({"approval_date"}),
    "request_date": frozenset({"request_date"}),
    "work_date": frozenset({"work_date"}),
    "processing_date": frozenset({"processing_date"}),
    "per_claim": frozenset(
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
    ),
}


@dataclass(frozen=True)
class EditionMetadata:
    """manifest 한 항목(검수된 값). 원문에서 알 수 없는 값을 MOD-05가 채우지 않는다."""

    source_file_id: str
    document_key: str
    version: str
    filename: str
    title: str
    domain: str
    document_type: str
    source_document_number: str
    document_role: str
    application_basis: str
    basis_evidence: tuple[dict[str, Any], ...]
    available_from: datetime
    effective_from: date | None
    effective_to: date | None
    guidance_valid_from: datetime | None
    guidance_valid_to: datetime | None
    supersedes_source_file_id: str | None
    edition_state: str
    owning_department: str | None
    access_policy: dict[str, Any]
    access_policy_source: str
    review_status: str
    transition_relations: tuple[dict[str, Any], ...] = ()
    authority_relations: tuple[dict[str, Any], ...] = ()
    related_document_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedChunk:
    ordinal: int
    support_group: int
    kind: str
    heading: str | None
    section_path: tuple[str, ...]
    text: str
    spans: tuple[dict[str, Any], ...]
    vector: tuple[float, ...]


@dataclass(frozen=True)
class PreparedEdition:
    metadata: EditionMetadata
    sha256: str
    page_count: int
    pages: tuple[dict[str, Any], ...]  # {page, text, blocks}
    chunks: tuple[PreparedChunk, ...]
    parser_revision: str
    chunk_config: str
    embedding_model: str
    embedding_dim: int
    embedding_format: str
    quality: dict[str, Any]

    @property
    def artifact_revision(self) -> str:
        embedding = f"{self.embedding_model}-{self.embedding_dim}"
        return f"{self.parser_revision}|{self.chunk_config}|{embedding}|{self.embedding_format}"


@dataclass(frozen=True)
class PreparedCorpus:
    editions: tuple[PreparedEdition, ...]
    manifest_hash: str
    config_hash: str
    label: str
    scope: str  # pilot | release


@dataclass(frozen=True)
class PublishResult:
    snapshot_id: str
    member_count: int
    pointer_revision: int


@dataclass(frozen=True)
class Passage:
    """CT-08 EvidencePassage. 허용되지 않은 자원은 만들지 않는다."""

    passage_id: str
    document_key: str
    edition_id: str
    source_file_id: str
    artifact_id: str
    corpus_snapshot_id: str
    title: str
    version: str
    document_type: str
    document_role: str
    application_basis: str
    edition_state: str
    available_from: datetime
    effective_from: date | None
    effective_to: date | None
    support_group: int
    kind: str
    heading: str | None
    section_path: tuple[str, ...]
    text: str
    page_spans: tuple[dict[str, Any], ...]
    token_estimate: int
    acl_revision: int
    distance: float | None = None
    rank: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BasisHint:
    """LookupApplicableBasis 결과. 답변용 passage가 아니라 검수 메타데이터만."""

    document_key: str
    document_role: str
    application_basis: str
