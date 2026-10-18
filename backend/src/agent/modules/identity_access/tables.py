"""MOD-09 테이블(SQLAlchemy Core). 사용자·부서·역할·세션·auth_revision의 단일 쓰기 소유자는 MOD-09다."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

departments = Table(
    "departments",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
)

roles = Table(
    "roles",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
)

# 역할 → capability(CT-01 닫힌 이름). 값은 데모 조직 fixture(D-30)에서만 적재한다.
role_capabilities = Table(
    "role_capabilities",
    metadata,
    Column("role_id", Text, ForeignKey("roles.id"), primary_key=True),
    Column("capability", Text, primary_key=True),
)

users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    # 검증된 해시만 저장한다(scrypt). 웹 로그인이 없는 계정(운영 CLI)은 NULL.
    Column("password_hash", Text),
    Column("web_login", Boolean, nullable=False),
    Column("active", Boolean, nullable=False),
    # 부서·역할이 바뀔 때마다 증가한다. 요청 시작 때의 actor 사본이 오래됐는지 판정한다.
    Column("auth_revision", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # 사내 회신 수단(서버 프로필 값, M5). 티켓 requester/reply_channel은 모델이 정하지 않는다.
    Column("reply_channel", Text),
)

user_departments = Table(
    "user_departments",
    metadata,
    Column("user_id", Text, ForeignKey("users.id"), primary_key=True),
    Column("department_id", Text, ForeignKey("departments.id"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", Text, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Text, ForeignKey("roles.id"), primary_key=True),
)

# 세션 토큰 원문은 저장하지 않는다(SHA-256만). 회수·만료는 행으로 판정한다.
auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

# 부서·역할 변경 감사(MOD-09 소유). 비밀 값은 넣지 않는다.
membership_audit = Table(
    "membership_audit",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("actor_id", Text, nullable=False),
    Column("actor_source", Text, nullable=False),
    Column("user_id", Text, nullable=False),
    Column("before", JSONB, nullable=False),
    Column("after", JSONB, nullable=False),
    Column("auth_revision", Integer, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)
