"""Date/time helpers. Working-day logic is pure so it can be unit-tested."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

DEFAULT_WEEKEND_DAYS = (5, 6)  # Monday=0 ... Sunday=6


def tz() -> ZoneInfo:
    return ZoneInfo(config.APP_TIMEZONE)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_local() -> date:
    return datetime.now(tz()).date()


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz())


def fmt_dt(dt: datetime | None) -> str:
    local = to_local(dt)
    return local.strftime("%d %b %Y %H:%M") if local else "—"


def fmt_date(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else "—"


def iter_days(start: date, end: date):
    for i in range((end - start).days + 1):
        yield start + timedelta(days=i)


def working_dates(start: date, end: date, holidays=frozenset(), weekend_days=DEFAULT_WEEKEND_DAYS) -> list[date]:
    """Dates in [start, end] that are neither weekend days nor company holidays."""
    if end < start:
        return []
    return [d for d in iter_days(start, end) if d.weekday() not in weekend_days and d not in holidays]


def count_working_days(start: date, end: date, holidays=frozenset(), weekend_days=DEFAULT_WEEKEND_DAYS) -> int:
    return len(working_dates(start, end, holidays, weekend_days))


def ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    return start_a <= end_b and start_b <= end_a
