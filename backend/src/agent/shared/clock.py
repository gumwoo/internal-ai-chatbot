"""CP-01 Clock. 업무 시각은 KST, 시간 초과 측정은 단조 시계를 쓴다(CT-02)."""

import time
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 첫 구간 고정 fixture의 기준 시각(docs/12-first-milestone-spec.md).
FIXTURE_NOW = datetime(2026, 10, 16, 10, 0, tzinfo=KST)


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(KST)

    def monotonic(self) -> float:
        return time.monotonic()


class FixedClock:
    """테스트용 고정 시계. advance로만 시간이 흐른다."""

    def __init__(self, at: datetime = FIXTURE_NOW) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock에는 시간대가 있는 시각이 필요하다")
        self._now = at.astimezone(KST)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds
