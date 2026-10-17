"""MOD-04 교육 조회. T-11 날짜 경계·페이지·제목·취소 제외, T-12 상세·미존재·seed 재실행.

기준 시각은 고정 fixture의 2026-10-16(금) 10:00 KST다.
"""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from agent.app.main import create_app
from agent.modules.training.dates import resolve_range
from agent.modules.training.fixtures import FIXTURES
from agent.modules.training.models import TrainingSearchInput
from agent.modules.training.service import TrainingService, load_demo_trainings
from agent.shared.clock import FIXTURE_NOW, KST, FixedClock
from agent.shared.errors import AppError, ErrorCode
from tests.conftest import api_client, make_settings

SEC_ID = UUID("11111111-1111-4111-8111-111111111101")


def _range(**kwargs):
    resolved = resolve_range(TrainingSearchInput(**kwargs), FIXTURE_NOW)
    return resolved.start_date, resolved.end_date_exclusive


# --- 날짜 해석(DB 없음) ---


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("today", (date(2026, 10, 16), date(2026, 10, 17))),
        ("this_week", (date(2026, 10, 12), date(2026, 10, 19))),
        ("next_week", (date(2026, 10, 19), date(2026, 10, 26))),
        ("next_30_days", (date(2026, 10, 16), date(2026, 11, 15))),
    ],
)
def test_presets_match_spec_table(preset, expected):
    assert _range(date_preset=preset) == expected


def test_default_preset_is_next_30_days():
    assert _range() == (date(2026, 10, 16), date(2026, 11, 15))


def test_week_starts_on_monday_even_on_sunday():
    sunday = datetime(2026, 10, 18, 23, 59, tzinfo=KST)
    resolved = resolve_range(TrainingSearchInput(date_preset="this_week"), sunday)
    assert (resolved.start_date, resolved.end_date_exclusive) == (date(2026, 10, 12), date(2026, 10, 19))


def test_today_uses_kst_date_not_utc():
    # UTC로는 10/15 16:00이지만 KST로는 10/16 01:00이다.
    utc_now = datetime(2026, 10, 15, 16, 0, tzinfo=UTC)
    resolved = resolve_range(TrainingSearchInput(date_preset="today"), utc_now)
    assert resolved.start_date == date(2026, 10, 16)


@pytest.mark.parametrize(
    ("kwargs", "fields"),
    [
        ({"date_preset": "custom"}, ["end_date_exclusive", "start_date"]),
        ({"date_preset": "custom", "start_date": "2026-10-20"}, ["end_date_exclusive"]),
        (
            {"date_preset": "custom", "start_date": "2026-10-20", "end_date_exclusive": "2026-10-20"},
            ["end_date_exclusive", "start_date"],
        ),
        (
            {"date_preset": "custom", "start_date": "2026-10-01", "end_date_exclusive": "2026-12-31"},
            ["end_date_exclusive", "start_date"],
        ),
        ({"date_preset": "next_week", "start_date": "2026-10-20"}, ["date_preset"]),
    ],
)
def test_invalid_ranges_are_rejected_with_field_names(kwargs, fields):
    with pytest.raises(AppError) as info:
        _range(**kwargs)
    assert info.value.code is ErrorCode.INVALID_REQUEST
    assert info.value.details == {"field_names": fields}


def test_custom_range_allows_exactly_90_days():
    assert _range(date_preset="custom", start_date="2026-10-01", end_date_exclusive="2026-12-30") == (
        date(2026, 10, 1),
        date(2026, 12, 30),
    )


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": 0}, {"limit": 21}, {"offset": -1}, {"query": "가" * 101}, {"user_id": "admin"}],
)
def test_input_bounds_and_unknown_fields(kwargs):
    with pytest.raises(ValidationError):
        TrainingSearchInput(**kwargs)


def test_fixture_ids_and_codes_are_unique_and_fixed():
    assert len({f.id for f in FIXTURES}) == len({f.code for f in FIXTURES}) == 10
    assert FIXTURES[0].id == SEC_ID
    assert FIXTURES[1].id == UUID("11111111-1111-4111-8111-111111111102")


# --- DB 조회 ---


async def _codes(engine, **kwargs) -> list[str]:
    page = await TrainingService(engine).list_trainings(TrainingSearchInput(**kwargs), FIXTURE_NOW)
    return [item.code for item in page.items]


async def test_acceptance_ranges(seeded_engine):
    assert await _codes(seeded_engine, date_preset="next_week") == ["TR-SEC-001", "TR-COLLAB-001"]
    assert await _codes(seeded_engine, date_preset="today") == ["TR-ONBOARD-001"]
    # 이번 주의 completed(10/13, 10/15)는 기본 목록에서 빠진다.
    assert await _codes(seeded_engine, date_preset="this_week") == ["TR-ONBOARD-001"]
    # scheduled 7건, 취소된 개인정보 교육(10/21)은 빠진다.
    assert len(await _codes(seeded_engine)) == 7
    assert "TR-PRIVACY-001" not in await _codes(seeded_engine)


async def test_next_week_excludes_range_end(seeded_engine):
    # 10/26 09:00 데이터 활용 기초는 [10/19, 10/26) 밖이다.
    assert "TR-DATA-001" not in await _codes(seeded_engine, date_preset="next_week")


async def test_today_includes_earlier_hour_than_now(seeded_engine):
    """현재 10시여도 오늘 09시 scheduled는 포함한다(현재 시각 이후 필터 없음)."""
    async with seeded_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO trainings (id, code, title, description, starts_at, ends_at, location, status)"
                " VALUES (gen_random_uuid(), 'TR-EARLY-TEST', '아침 교육', '테스트용',"
                " '2026-10-16 09:00+09', '2026-10-16 09:30+09', '온라인', 'scheduled')"
            )
        )
    assert await _codes(seeded_engine, date_preset="today") == ["TR-EARLY-TEST", "TR-ONBOARD-001"]


async def test_title_query_is_case_insensitive_partial_and_escaped(seeded_engine):
    assert await _codes(seeded_engine, query="보안") == ["TR-SEC-001"]
    assert await _codes(seeded_engine, query="%") == []
    assert await _codes(seeded_engine, query="없는 교육") == []


async def test_paging(seeded_engine):
    service = TrainingService(seeded_engine)
    first = await service.list_trainings(TrainingSearchInput(limit=3), FIXTURE_NOW)
    second = await service.list_trainings(TrainingSearchInput(limit=3, offset=3), FIXTURE_NOW)
    assert (first.total, first.has_more, len(first.items)) == (7, True, 3)
    assert {i.code for i in first.items}.isdisjoint({i.code for i in second.items})
    last = await service.list_trainings(TrainingSearchInput(limit=3, offset=6), FIXTURE_NOW)
    assert (len(last.items), last.has_more) == (1, False)


async def test_detail_returns_real_status_and_kst_times(seeded_engine):
    service = TrainingService(seeded_engine)
    detail = await service.get_training(UUID("11111111-1111-4111-8111-111111111105"))
    assert detail.status == "cancelled"
    sec = await service.get_training(SEC_ID)
    assert sec.location == "3층 교육장"
    assert sec.starts_at.isoformat() == "2026-10-20T14:00:00+09:00"


async def test_missing_training_is_not_found(seeded_engine):
    with pytest.raises(AppError) as info:
        await TrainingService(seeded_engine).get_training(UUID("11111111-1111-4111-8111-999999999999"))
    assert info.value.code is ErrorCode.TRAINING_NOT_FOUND


async def test_seed_rerun_does_not_duplicate(seeded_engine):
    report = await load_demo_trainings(
        seeded_engine, anchor_date=date(2026, 10, 16), fixture_mode="fixed_status", now=FIXTURE_NOW
    )
    async with seeded_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM trainings"))
    assert (report.loaded, report.shift_days, count) == (10, 0, 10)


async def test_seed_anchor_shift_keeps_weekday_and_time(seeded_engine):
    anchor = date(2026, 11, 4)  # 수요일 → 그 주 월요일 11/2, 기준 10/12와 21일 차이
    report = await load_demo_trainings(
        seeded_engine, anchor_date=anchor, fixture_mode="fixed_status", now=FIXTURE_NOW
    )
    sec = await TrainingService(seeded_engine).get_training(SEC_ID)
    assert report.shift_days == 21
    assert sec.starts_at.isoformat() == "2026-11-10T14:00:00+09:00"
    assert sec.starts_at.weekday() == 1  # 화요일 유지


async def test_seed_live_clock_recomputes_status_but_keeps_cancelled(seeded_engine):
    later = datetime(2026, 10, 21, 0, 0, tzinfo=KST)
    await load_demo_trainings(
        seeded_engine, anchor_date=date(2026, 10, 16), fixture_mode="live_clock", now=later
    )
    service = TrainingService(seeded_engine)
    assert (await service.get_training(SEC_ID)).status == "completed"  # 10/20 16시 종료
    assert (await service.get_training(UUID("11111111-1111-4111-8111-111111111105"))).status == "cancelled"
    assert (await service.get_training(UUID("11111111-1111-4111-8111-111111111102"))).status == "scheduled"


# --- HTTP ---


async def test_http_list_and_detail(seeded_engine, migrated):
    app = create_app(make_settings(database_url=migrated), clock=FixedClock())
    async with api_client(app) as client:
        listed = await client.get("/api/v1/trainings", params={"date_preset": "next_week"})
        detail = await client.get(f"/api/v1/trainings/{SEC_ID}")
        bad_uuid = await client.get("/api/v1/trainings/not-a-uuid")
        missing = await client.get("/api/v1/trainings/11111111-1111-4111-8111-999999999999")
        unknown = await client.get("/api/v1/trainings", params={"user_id": "admin"})
        too_long = await client.get(
            "/api/v1/trainings",
            params={"date_preset": "custom", "start_date": "2026-10-01", "end_date_exclusive": "2027-01-31"},
        )
    assert listed.status_code == 200
    body = listed.json()
    assert [i["code"] for i in body["items"]] == ["TR-SEC-001", "TR-COLLAB-001"]
    assert body["resolved_range"] == {
        "date_preset": "next_week",
        "start_date": "2026-10-19",
        "end_date_exclusive": "2026-10-26",
    }
    assert detail.json()["description"]
    assert bad_uuid.status_code == 422
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "TRAINING_NOT_FOUND")
    assert (unknown.status_code, unknown.json()["error"]["details"]) == (422, {"field_names": ["user_id"]})
    assert too_long.status_code == 422


async def test_http_requires_training_capability(seeded_engine, migrated):
    from agent.shared.actor import ActorContext

    class NoCapabilities:
        async def resolve(self, request):
            return ActorContext("x", (), (), frozenset(), 1, "test_stub")

    app = create_app(make_settings(database_url=migrated), current_actor=NoCapabilities())
    async with api_client(app) as client:
        response = await client.get("/api/v1/trainings")
    assert (response.status_code, response.json()["error"]["code"]) == (403, "ACTION_NOT_ALLOWED")
