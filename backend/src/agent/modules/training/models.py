"""CT-04 TrainingSearchInput, CT-05 TrainingPage/Detail."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DatePreset(StrEnum):
    TODAY = "today"
    THIS_WEEK = "this_week"
    NEXT_WEEK = "next_week"
    NEXT_30_DAYS = "next_30_days"
    CUSTOM = "custom"


TrainingStatus = Literal["scheduled", "completed", "cancelled"]


class TrainingSearchInput(BaseModel):
    """HTTP 쿼리와 list_trainings 도구 인자가 같은 모델을 쓴다. 정의되지 않은 필드는 거절한다."""

    model_config = ConfigDict(extra="forbid")

    date_preset: DatePreset = DatePreset.NEXT_30_DAYS
    start_date: date | None = None
    end_date_exclusive: date | None = None
    query: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class ResolvedRange(BaseModel):
    date_preset: DatePreset
    start_date: date
    end_date_exclusive: date


class TrainingSummary(BaseModel):
    id: UUID
    code: str
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str
    status: TrainingStatus


class TrainingDetail(TrainingSummary):
    description: str


class TrainingPage(BaseModel):
    items: list[TrainingSummary]
    total: int
    limit: int
    offset: int
    has_more: bool
    resolved_range: ResolvedRange
