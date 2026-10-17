"""MOD-04 공개 작업: ListTrainings, GetTraining, LoadDemoTrainings. HTTP와 도구가 같은 함수를 쓴다."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from agent.modules.training import repository
from agent.modules.training.dates import kst_midnight, resolve_range
from agent.modules.training.fixtures import BASE_MONDAY, FIXTURES, TrainingFixture
from agent.modules.training.models import (
    TrainingDetail,
    TrainingPage,
    TrainingSearchInput,
    TrainingStatus,
    TrainingSummary,
)
from agent.shared.clock import KST
from agent.shared.errors import AppError, ErrorCode

FixtureMode = Literal["fixed_status", "live_clock"]


def _summary(row: Any) -> TrainingSummary:
    return TrainingSummary(
        id=row.id,
        code=row.code,
        title=row.title,
        starts_at=row.starts_at.astimezone(KST),
        ends_at=row.ends_at.astimezone(KST),
        location=row.location,
        status=row.status,
    )


class TrainingService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def list_trainings(self, search: TrainingSearchInput, now: datetime) -> TrainingPage:
        resolved = resolve_range(search, now)
        async with self._engine.connect() as conn:
            rows, total = await repository.list_scheduled(
                conn,
                start=kst_midnight(resolved.start_date),
                end=kst_midnight(resolved.end_date_exclusive),
                query=search.query,
                limit=search.limit,
                offset=search.offset,
            )
        items = [_summary(row) for row in rows]
        return TrainingPage(
            items=items,
            total=total,
            limit=search.limit,
            offset=search.offset,
            has_more=search.offset + len(items) < total,
            resolved_range=resolved,
        )

    async def get_training(self, training_id: UUID) -> TrainingDetail:
        async with self._engine.connect() as conn:
            row = await repository.get(conn, training_id)
        if row is None:
            raise AppError(ErrorCode.TRAINING_NOT_FOUND)
        return TrainingDetail(**_summary(row).model_dump(), description=row.description)


@dataclass(frozen=True)
class LoadReport:
    anchor_date: date
    fixture_mode: FixtureMode
    clock: datetime
    shift_days: int
    loaded: int


def _status(fixture: TrainingFixture, ends_at: datetime, mode: FixtureMode, now: datetime) -> TrainingStatus:
    if mode == "fixed_status" or fixture.status_override == "cancelled":
        return fixture.status_override
    return "completed" if ends_at <= now else "scheduled"


async def load_demo_trainings(
    engine: AsyncEngine, *, anchor_date: date, fixture_mode: FixtureMode, now: datetime
) -> LoadReport:
    """개발/테스트 CLI 전용. anchor가 속한 주의 월요일로 fixture 날짜를 평행 이동해 덮어쓴다."""
    target_monday = anchor_date - timedelta(days=anchor_date.weekday())
    shift = target_monday - BASE_MONDAY
    values = []
    for fixture in FIXTURES:
        starts_at = fixture.starts_at + shift
        ends_at = fixture.ends_at + shift
        values.append(
            {
                "id": fixture.id,
                "code": fixture.code,
                "title": fixture.title,
                "description": fixture.description,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "location": fixture.location,
                "status": _status(fixture, ends_at, fixture_mode, now),
            }
        )
    async with engine.begin() as conn:
        await repository.upsert_many(conn, values)
    return LoadReport(
        anchor_date=anchor_date,
        fixture_mode=fixture_mode,
        clock=now,
        shift_days=shift.days,
        loaded=len(values),
    )
