"""MOD-09 사용자·부서·역할·세션 테이블(docs/03-data-model.md, modules/MOD-09).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.create_table(
        "role_capabilities",
        sa.Column("role_id", sa.Text(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("capability", sa.Text(), primary_key=True),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("web_login", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("auth_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("auth_revision >= 1", name="ck_users_auth_revision"),
        # 웹 로그인 계정에는 비밀번호 해시가 있어야 한다.
        sa.CheckConstraint("NOT web_login OR password_hash IS NOT NULL", name="ck_users_web_login_hash"),
    )
    op.create_table(
        "user_departments",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("department_id", sa.Text(), sa.ForeignKey("departments.id"), primary_key=True),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", sa.Text(), sa.ForeignKey("roles.id"), primary_key=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
    )
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_id"])
    op.create_table(
        "membership_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("actor_source", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("before", JSONB, nullable=False),
        sa.Column("after", JSONB, nullable=False),
        sa.Column("auth_revision", sa.Integer(), nullable=False),
        sa.Column("changed_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("membership_audit")
    op.drop_index("ix_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("user_roles")
    op.drop_table("user_departments")
    op.drop_table("users")
    op.drop_table("role_capabilities")
    op.drop_table("roles")
    op.drop_table("departments")
