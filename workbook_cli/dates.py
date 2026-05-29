from __future__ import annotations

from datetime import datetime, timedelta

from .config import DAY_NAMES


def week_start(week_offset: int = 0) -> datetime:
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(weeks=week_offset)


def workbook_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")


def week_dates(week_offset: int = 0) -> dict[str, str]:
    monday = week_start(week_offset)
    return {
        day: workbook_date(monday + timedelta(days=index))
        for index, day in enumerate(DAY_NAMES)
    }


def day_name_from_registration_date(value: str) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if 0 <= dt.weekday() < len(DAY_NAMES):
        return DAY_NAMES[dt.weekday()]
    return None
