from datetime import UTC, datetime, timedelta

import pytest

from agent.shared.clock import FIXTURE_NOW, KST, FixedClock, SystemClock


def test_fixed_clock_defaults_to_fixture_time():
    clock = FixedClock()
    assert clock.now() == FIXTURE_NOW
    assert clock.now().isoformat() == "2026-10-16T10:00:00+09:00"


def test_fixed_clock_converts_to_kst_and_advances_both_clocks():
    clock = FixedClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    assert clock.now().utcoffset() == timedelta(hours=9)
    clock.advance(90)
    assert clock.now() == datetime(2026, 10, 16, 10, 1, 30, tzinfo=KST)
    assert clock.monotonic() == 90


def test_fixed_clock_refuses_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 10, 16, 10, 0))


def test_system_clock_is_kst():
    assert SystemClock().now().utcoffset() == timedelta(hours=9)
