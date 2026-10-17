"""trainings 테이블 접근(SQLAlchemy Core). 이 모듈 밖에서는 테이블을 직접 읽지 않는다."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    Table,
    Text,
    and_,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

metadata = MetaData()

trainings = Table(
    "trainings",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("starts_at", DateTime(timezone=True), nullable=False, index=True),
    Column("ends_at", DateTime(timezone=True), nullable=False),
    Column("location", Text, nullable=False),
    Column("status", Text, nullable=False),
    CheckConstraint("status IN ('scheduled', 'completed', 'cancelled')", name="ck_trainings_status"),
    CheckConstraint("ends_at > starts_at", name="ck_trainings_period"),
)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def list_scheduled(
    conn: AsyncConnection,
    *,
    start: datetime,
    end: datetime,
    query: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Any], int]:
    conditions = [
        trainings.c.status == "scheduled",
        trainings.c.starts_at >= start,
        trainings.c.starts_at < end,
    ]
    if query:
        conditions.append(trainings.c.title.ilike(f"%{_escape_like(query)}%", escape="\\"))
    where = and_(*conditions)
    total = await conn.scalar(select(func.count()).select_from(trainings).where(where))
    rows = (
        await conn.execute(
            select(trainings)
            .where(where)
            .order_by(trainings.c.starts_at, trainings.c.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return rows, int(total or 0)


async def get(conn: AsyncConnection, training_id: UUID) -> Any | None:
    return (await conn.execute(select(trainings).where(trainings.c.id == training_id))).first()


async def upsert_many(conn: AsyncConnection, values: list[dict[str, Any]]) -> None:
    """id 기준으로 덮어쓴다. 재실행해도 행이 늘지 않는다."""
    stmt = insert(trainings).values(values)
    update_cols = {c.name: stmt.excluded[c.name] for c in trainings.c if c.name != "id"}
    await conn.execute(stmt.on_conflict_do_update(index_elements=[trainings.c.id], set_=update_cols))
