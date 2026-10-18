"""MOD-10 Wiki 테이블(SQLAlchemy Core). 빌드·page·주장·원문 링크·임베딩·snapshot·포인터의 단일 쓰기 소유자.

다른 모듈은 이 테이블을 직접 읽거나 쓰지 않는다(MOD-11은 GetCandidates 공개 작업만 쓴다).
원문 판본·passage ID는 MOD-05 소유라 외래 키 없이 값으로만 둔다.
"""

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from agent.modules.knowledge.tables import EMBEDDING_DIM, Vector

metadata = MetaData()
TS = DateTime(timezone=True)
UUID = PG_UUID(as_uuid=True)
POINTER = "active"

wiki_builds = Table(
    "wiki_builds",
    metadata,
    Column("build_id", UUID, primary_key=True),
    Column("corpus_snapshot_id", UUID, nullable=False),
    Column("scope", Text, nullable=False),
    Column("topic_plan_hash", Text, nullable=False),
    Column("config_id", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("model_id", Text, nullable=False),
    Column("embedding_model", Text, nullable=False),
    Column("status", Text, nullable=False),  # draft/validated/failed/published/retired
    Column("report", JSONB, nullable=False),
    Column("usage", JSONB, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
)

wiki_pages = Table(
    "wiki_pages",
    metadata,
    Column("page_id", UUID, primary_key=True),
    Column("build_id", UUID, ForeignKey("wiki_builds.build_id"), nullable=False),
    Column("topic_key", Text, nullable=False),
    Column("segment_key", Text, nullable=False),
    Column("acl_class", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("search_text", Text, nullable=False),
    Column("valid_from", Date),
    Column("valid_to", Date),
    Column("knowledge_from", TS, nullable=False),
    Column("knowledge_to", TS),
    Column("contributor_edition_ids", JSONB, nullable=False),
    Column("source_hash", Text, nullable=False),
    Column("status", Text, nullable=False),  # valid/excluded
    Column("problems", JSONB, nullable=False),
    Column("review_status", Text, nullable=False),  # pending/approved/rejected
    Column("review", JSONB),
    Column("usage", JSONB, nullable=False),
)

wiki_claims = Table(
    "wiki_claims",
    metadata,
    Column("claim_id", UUID, primary_key=True),
    Column("page_id", UUID, ForeignKey("wiki_pages.page_id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("kind", Text, nullable=False),  # claim/relation
    Column("text", Text, nullable=False),
)

wiki_source_links = Table(
    "wiki_source_links",
    metadata,
    Column("link_id", UUID, primary_key=True),
    Column("claim_id", UUID, ForeignKey("wiki_claims.claim_id"), nullable=False),
    Column("page_id", UUID, ForeignKey("wiki_pages.page_id"), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("edition_id", UUID, nullable=False),
    Column("passage_id", UUID, nullable=False),
    Column("quote", Text, nullable=False),
)

wiki_embeddings = Table(
    "wiki_embeddings",
    metadata,
    Column("page_id", UUID, ForeignKey("wiki_pages.page_id"), primary_key=True),
    Column("model", Text, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
)

wiki_snapshots = Table(
    "wiki_snapshots",
    metadata,
    Column("snapshot_id", UUID, primary_key=True),
    Column("build_id", UUID, ForeignKey("wiki_builds.build_id"), nullable=False, unique=True),
    Column("corpus_snapshot_id", UUID, nullable=False),
    Column("page_count", Integer, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TS, nullable=False),
)

wiki_snapshot_members = Table(
    "wiki_snapshot_members",
    metadata,
    Column("snapshot_id", UUID, ForeignKey("wiki_snapshots.snapshot_id"), primary_key=True),
    Column("page_id", UUID, ForeignKey("wiki_pages.page_id"), primary_key=True),
)

wiki_pointer = Table(
    "wiki_pointer",
    metadata,
    Column("name", Text, primary_key=True),
    Column("snapshot_id", UUID, ForeignKey("wiki_snapshots.snapshot_id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("updated_at", TS, nullable=False),
)
