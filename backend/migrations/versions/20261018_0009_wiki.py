"""MOD-10 Wiki 테이블(빌드·page·주장·원문 링크·임베딩·snapshot·게시 포인터)과 검색 전략 기록 칸(M4).

- Wiki는 원문 corpus snapshot 하나에 묶인다. page의 기여 원문 판본은 MOD-05 소유라 외래 키를 걸지 않는다.
- conversations.retrieval_strict: 평가 포트만 켠다(엄격 B는 fallback 대신 실패로 기록, docs/13).
- tool_calls.retrieval_trace: 모델에 보이지 않는 검색 경로(전략·fallback 이유·Wiki 후보·후보 passage).
- agent_runs.evidence_trace: 근거 예산 안에 실제로 들어간 passage(Recall@budget).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()
UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("retrieval_strict", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("tool_calls", sa.Column("retrieval_trace", JSONB))
    # 모델 문맥에 실제로 들어간 passage(근거 예산 조립 결과). 평가의 Recall@budget 계산용, 모델에 보이지 않음.
    op.add_column("agent_runs", sa.Column("evidence_trace", JSONB))
    op.create_table(
        "wiki_builds",
        sa.Column("build_id", UUID, primary_key=True),
        sa.Column("corpus_snapshot_id", UUID, nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("topic_plan_hash", sa.Text(), nullable=False),
        sa.Column("config_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        # draft/validated/failed/published/retired. stale은 저장하지 않고 corpus 포인터와 비교해 판정한다.
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("report", JSONB, nullable=False),
        sa.Column("usage", JSONB, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "wiki_pages",
        sa.Column("page_id", UUID, primary_key=True),
        sa.Column("build_id", UUID, sa.ForeignKey("wiki_builds.build_id"), nullable=False),
        sa.Column("topic_key", sa.Text(), nullable=False),
        sa.Column("segment_key", sa.Text(), nullable=False),
        sa.Column("acl_class", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        # 사건 날짜 축(규범 판본의 시행 구간 교집합). null은 열린 끝.
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        # 지식 시점 축(기여 원문의 공개 시각 최댓값, 안내 판본 유효 끝의 최솟값).
        sa.Column("knowledge_from", TS, nullable=False),
        sa.Column("knowledge_to", TS),
        sa.Column("contributor_edition_ids", JSONB, nullable=False),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),  # valid/excluded
        sa.Column("problems", JSONB, nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),  # pending/approved/rejected
        sa.Column("review", JSONB),
        sa.Column("usage", JSONB, nullable=False),
    )
    op.create_index("wiki_pages_build", "wiki_pages", ["build_id"])
    op.create_table(
        "wiki_claims",
        sa.Column("claim_id", UUID, primary_key=True),
        sa.Column("page_id", UUID, sa.ForeignKey("wiki_pages.page_id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # claim/relation
        sa.Column("text", sa.Text(), nullable=False),
        sa.UniqueConstraint("page_id", "ordinal"),
    )
    op.create_table(
        "wiki_source_links",
        sa.Column("link_id", UUID, primary_key=True),
        sa.Column("claim_id", UUID, sa.ForeignKey("wiki_claims.claim_id"), nullable=False),
        sa.Column("page_id", UUID, sa.ForeignKey("wiki_pages.page_id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("edition_id", UUID, nullable=False),
        sa.Column("passage_id", UUID, nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.UniqueConstraint("claim_id", "ordinal"),
    )
    op.create_index("wiki_source_links_page", "wiki_source_links", ["page_id"])
    op.create_table(
        "wiki_embeddings",
        sa.Column("page_id", UUID, sa.ForeignKey("wiki_pages.page_id"), primary_key=True),
        sa.Column("model", sa.Text(), nullable=False),
    )
    op.execute("ALTER TABLE wiki_embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_table(
        "wiki_snapshots",
        sa.Column("snapshot_id", UUID, primary_key=True),
        sa.Column("build_id", UUID, sa.ForeignKey("wiki_builds.build_id"), nullable=False, unique=True),
        sa.Column("corpus_snapshot_id", UUID, nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "wiki_snapshot_members",
        sa.Column("snapshot_id", UUID, sa.ForeignKey("wiki_snapshots.snapshot_id"), primary_key=True),
        sa.Column("page_id", UUID, sa.ForeignKey("wiki_pages.page_id"), primary_key=True),
    )
    op.create_table(
        "wiki_pointer",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("snapshot_id", UUID, sa.ForeignKey("wiki_snapshots.snapshot_id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )


def downgrade() -> None:
    for name in (
        "wiki_pointer",
        "wiki_snapshot_members",
        "wiki_snapshots",
        "wiki_embeddings",
        "wiki_source_links",
        "wiki_claims",
        "wiki_pages",
        "wiki_builds",
    ):
        op.drop_table(name)
    op.execute("ALTER TABLE agent_runs DROP COLUMN IF EXISTS evidence_trace")
    op.drop_column("tool_calls", "retrieval_trace")
    op.drop_column("conversations", "retrieval_strict")
