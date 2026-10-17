"""MOD-05 지식 테이블(SQLAlchemy Core). 원문·판본·청크·임베딩·corpus snapshot·자원 ACL의 단일 쓰기 소유자.

다른 모듈은 이 테이블을 직접 읽거나 쓰지 않는다(MOD-11은 MOD-05의 공개 작업으로만 검색한다).
"""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import UserDefinedType

EMBEDDING_DIM = 1536  # D-32. 바꾸면 컬럼 차원이 바뀌므로 마이그레이션과 재색인이 필요하다.


class Vector(UserDefinedType):
    """pgvector vector(n). 파이썬 쪽은 float 튜플."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(repr(float(v)) for v in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None or isinstance(value, (list, tuple)):
                return value
            return tuple(float(v) for v in value.strip("[]").split(","))

        return process


metadata = MetaData()
UUID = PG_UUID(as_uuid=True)
TS = DateTime(timezone=True)

logical_documents = Table(
    "logical_documents",
    metadata,
    Column("document_key", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("domain", Text, nullable=False),
    Column("owning_department", Text),
    Column("created_at", TS, nullable=False),
)

# 문서 키 단위의 현재 ACL. 판본·과거 시점과 무관하게 현재 정책으로 판정한다(D-04, D-31).
resource_acl = Table(
    "resource_acl",
    metadata,
    Column("document_key", Text, ForeignKey("logical_documents.document_key"), primary_key=True),
    Column("policy", JSONB, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("source", Text, nullable=False),
    Column("updated_at", TS, nullable=False),
)

acl_audit = Table(
    "acl_audit",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("document_key", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("before", JSONB),
    Column("after", JSONB, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("changed_at", TS, nullable=False),
)

source_files = Table(
    "source_files",
    metadata,
    Column("source_file_id", Text, primary_key=True),
    Column("filename", Text, nullable=False),
    Column("sha256", Text, nullable=False, unique=True),
    Column("page_count", Integer, nullable=False),
    Column("registered_at", TS, nullable=False),
)

document_editions = Table(
    "document_editions",
    metadata,
    Column("edition_id", UUID, primary_key=True),
    Column("document_key", Text, ForeignKey("logical_documents.document_key"), nullable=False),
    Column("version", Text, nullable=False),
    Column("source_file_id", Text, ForeignKey("source_files.source_file_id"), nullable=False, unique=True),
    Column("source_document_number", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("document_type", Text, nullable=False),
    Column("document_role", Text, nullable=False),  # normative | guidance
    Column("application_basis", Text, nullable=False),
    Column("basis_evidence", JSONB, nullable=False),
    Column("available_from", TS, nullable=False),
    Column("effective_from", Date),
    Column("effective_to", Date),  # 종료 제외, null은 열린 구간
    Column("guidance_valid_from", TS),
    Column("guidance_valid_to", TS),
    Column("supersedes_source_file_id", Text),
    Column("edition_state", Text, nullable=False),  # current | superseded | withdrawn
    Column("transition_relations", JSONB, nullable=False),
    Column("authority_relations", JSONB, nullable=False),
    Column("related_document_keys", JSONB, nullable=False),
    Column("review_status", Text, nullable=False),
    Column("registered_at", TS, nullable=False),
    UniqueConstraint("document_key", "version", name="uq_editions_key_version"),
)

parsed_artifacts = Table(
    "parsed_artifacts",
    metadata,
    Column("artifact_id", UUID, primary_key=True),
    Column("edition_id", UUID, ForeignKey("document_editions.edition_id"), nullable=False),
    Column("artifact_revision", Text, nullable=False),
    Column("parser_revision", Text, nullable=False),
    Column("chunk_config", Text, nullable=False),
    Column("embedding_model", Text, nullable=False),
    Column("embedding_dim", Integer, nullable=False),
    Column("embedding_format", Text, nullable=False),
    Column("quality", JSONB, nullable=False),
    Column("created_at", TS, nullable=False),
    UniqueConstraint("edition_id", "artifact_revision", name="uq_artifacts_edition_revision"),
)

document_pages = Table(
    "document_pages",
    metadata,
    Column("artifact_id", UUID, ForeignKey("parsed_artifacts.artifact_id"), primary_key=True),
    Column("page", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("blocks", JSONB, nullable=False),  # [{block_id, kind, start, end, bbox}]
)

chunks = Table(
    "chunks",
    metadata,
    Column("passage_id", UUID, primary_key=True),
    Column("artifact_id", UUID, ForeignKey("parsed_artifacts.artifact_id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("support_group", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("heading", Text),
    Column("section_path", JSONB, nullable=False),
    Column("text", Text, nullable=False),
    Column("spans", JSONB, nullable=False),
    Column("token_estimate", Integer, nullable=False),
    UniqueConstraint("artifact_id", "ordinal", name="uq_chunks_artifact_ordinal"),
)

chunk_embeddings = Table(
    "chunk_embeddings",
    metadata,
    Column("passage_id", UUID, ForeignKey("chunks.passage_id"), primary_key=True),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
)

corpus_snapshots = Table(
    "corpus_snapshots",
    metadata,
    Column("snapshot_id", UUID, primary_key=True),
    Column("label", Text, nullable=False),
    Column("scope", Text, nullable=False),  # pilot | release
    Column("manifest_hash", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("member_count", Integer, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
)

snapshot_members = Table(
    "snapshot_members",
    metadata,
    Column("snapshot_id", UUID, ForeignKey("corpus_snapshots.snapshot_id"), primary_key=True),
    Column("artifact_id", UUID, ForeignKey("parsed_artifacts.artifact_id"), primary_key=True),
)

# 게시 포인터. 검색은 이 행이 가리키는 snapshot만 본다. 전환은 한 행 갱신이라 원자적이다.
corpus_pointer = Table(
    "corpus_pointer",
    metadata,
    Column("name", Text, primary_key=True),
    Column("snapshot_id", UUID, ForeignKey("corpus_snapshots.snapshot_id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("updated_at", TS, nullable=False),
)
