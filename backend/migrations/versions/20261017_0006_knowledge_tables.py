"""MOD-05 원문·판본·청크·임베딩·corpus snapshot·자원 ACL 테이블(docs/03-data-model.md).

임베딩은 vector(1536)(D-32). 주 실험은 exact 검색이라 벡터 인덱스를 만들지 않는다(docs/06-rag-design).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "logical_documents",
        sa.Column("document_key", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("owning_department", sa.Text()),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "resource_acl",
        sa.Column(
            "document_key", sa.Text(), sa.ForeignKey("logical_documents.document_key"), primary_key=True
        ),
        sa.Column("policy", JSONB, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "acl_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("document_key", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changed_at", TS, nullable=False),
    )
    op.create_table(
        "source_files",
        sa.Column("source_file_id", sa.Text(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False, unique=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("registered_at", TS, nullable=False),
    )
    op.create_table(
        "document_editions",
        sa.Column("edition_id", UUID, primary_key=True),
        sa.Column("document_key", sa.Text(), sa.ForeignKey("logical_documents.document_key"), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "source_file_id",
            sa.Text(),
            sa.ForeignKey("source_files.source_file_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("source_document_number", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("document_role", sa.Text(), nullable=False),
        sa.Column("application_basis", sa.Text(), nullable=False),
        sa.Column("basis_evidence", JSONB, nullable=False),
        sa.Column("available_from", TS, nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("guidance_valid_from", TS),
        sa.Column("guidance_valid_to", TS),
        sa.Column("supersedes_source_file_id", sa.Text()),
        sa.Column("edition_state", sa.Text(), nullable=False),
        sa.Column("transition_relations", JSONB, nullable=False),
        sa.Column("authority_relations", JSONB, nullable=False),
        sa.Column("related_document_keys", JSONB, nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("registered_at", TS, nullable=False),
        sa.UniqueConstraint("document_key", "version", name="uq_editions_key_version"),
        sa.CheckConstraint("document_role IN ('normative', 'guidance')", name="ck_editions_role"),
        sa.CheckConstraint(
            "edition_state IN ('current', 'superseded', 'withdrawn')", name="ck_editions_state"
        ),
        # 규범 판본은 적용 시작일이 있어야 하고 구간이 비어 있으면 안 된다.
        sa.CheckConstraint(
            "document_role <> 'normative' OR effective_from IS NOT NULL", name="ck_editions_normative_from"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_from < effective_to",
            name="ck_editions_effective_range",
        ),
    )
    op.create_table(
        "parsed_artifacts",
        sa.Column("artifact_id", UUID, primary_key=True),
        sa.Column("edition_id", UUID, sa.ForeignKey("document_editions.edition_id"), nullable=False),
        sa.Column("artifact_revision", sa.Text(), nullable=False),
        sa.Column("parser_revision", sa.Text(), nullable=False),
        sa.Column("chunk_config", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_format", sa.Text(), nullable=False),
        sa.Column("quality", JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("edition_id", "artifact_revision", name="uq_artifacts_edition_revision"),
    )
    op.create_table(
        "document_pages",
        sa.Column("artifact_id", UUID, sa.ForeignKey("parsed_artifacts.artifact_id"), primary_key=True),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("blocks", JSONB, nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("passage_id", UUID, primary_key=True),
        sa.Column("artifact_id", UUID, sa.ForeignKey("parsed_artifacts.artifact_id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("support_group", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text()),
        sa.Column("section_path", JSONB, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("spans", JSONB, nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.UniqueConstraint("artifact_id", "ordinal", name="uq_chunks_artifact_ordinal"),
    )
    op.create_index("ix_chunks_group", "chunks", ["artifact_id", "support_group"])
    op.create_table(
        "chunk_embeddings",
        sa.Column("passage_id", UUID, sa.ForeignKey("chunks.passage_id"), primary_key=True),
    )
    op.execute("ALTER TABLE chunk_embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_table(
        "corpus_snapshots",
        sa.Column("snapshot_id", UUID, primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("scope IN ('pilot', 'release')", name="ck_snapshots_scope"),
    )
    op.create_table(
        "snapshot_members",
        sa.Column("snapshot_id", UUID, sa.ForeignKey("corpus_snapshots.snapshot_id"), primary_key=True),
        sa.Column("artifact_id", UUID, sa.ForeignKey("parsed_artifacts.artifact_id"), primary_key=True),
    )
    op.create_table(
        "corpus_pointer",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("snapshot_id", UUID, sa.ForeignKey("corpus_snapshots.snapshot_id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    for table in (
        "corpus_pointer",
        "snapshot_members",
        "corpus_snapshots",
        "chunk_embeddings",
    ):
        op.drop_table(table)
    op.drop_index("ix_chunks_group", table_name="chunks")
    for table in (
        "chunks",
        "document_pages",
        "parsed_artifacts",
        "document_editions",
        "source_files",
        "acl_audit",
        "resource_acl",
        "logical_documents",
    ):
        op.drop_table(table)
