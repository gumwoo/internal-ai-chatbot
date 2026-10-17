"""교육 기간 해석(CT-04). KST 00시 경계, 시작 포함·종료 제외, 주 시작은 월요일, 최대 90일."""

from datetime import date, datetime, time, timedelta

from agent.modules.training.models import DatePreset, ResolvedRange, TrainingSearchInput
from agent.shared.clock import KST
from agent.shared.errors import AppError, ErrorCode

MAX_RANGE_DAYS = 90


def _invalid(*field_names: str) -> AppError:
    return AppError(ErrorCode.INVALID_REQUEST, details={"field_names": sorted(field_names)})


def resolve_range(search: TrainingSearchInput, now: datetime) -> ResolvedRange:
    """서버 시각(now)으로 preset을 실제 날짜 구간으로 바꾼다. 현재 시각 이후라는 추가 필터는 없다."""
    today = now.astimezone(KST).date()
    preset = search.date_preset
    has_custom_dates = search.start_date is not None or search.end_date_exclusive is not None

    if preset is DatePreset.CUSTOM:
        missing = [
            name
            for name, value in (
                ("start_date", search.start_date),
                ("end_date_exclusive", search.end_date_exclusive),
            )
            if value is None
        ]
        if missing:
            raise _invalid(*missing)
        start, end = search.start_date, search.end_date_exclusive
        if start is None or end is None or end <= start or (end - start).days > MAX_RANGE_DAYS:
            raise _invalid("start_date", "end_date_exclusive")
        return ResolvedRange(date_preset=preset, start_date=start, end_date_exclusive=end)

    if has_custom_dates:
        # custom이 아닌데 날짜를 주면 어느 쪽을 따를지 모호하므로 거절한다.
        raise _invalid("date_preset")

    monday = today - timedelta(days=today.weekday())
    match preset:
        case DatePreset.TODAY:
            start, end = today, today + timedelta(days=1)
        case DatePreset.THIS_WEEK:
            start, end = monday, monday + timedelta(days=7)
        case DatePreset.NEXT_WEEK:
            start, end = monday + timedelta(days=7), monday + timedelta(days=14)
        case DatePreset.NEXT_30_DAYS:
            start, end = today, today + timedelta(days=30)
    return ResolvedRange(date_preset=preset, start_date=start, end_date_exclusive=end)


def kst_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=KST)
