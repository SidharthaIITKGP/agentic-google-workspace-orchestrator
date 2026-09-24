import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def normalize_temporal_expressions(
    text: str,
    reference: datetime,
    timezone_name: str,
) -> dict[str, dict[str, str]]:
    timezone = ZoneInfo(timezone_name)
    local_reference = reference.astimezone(timezone)
    today = local_reference.date()
    normalized: dict[str, dict[str, str]] = {}
    lowered = text.lower()

    single_dates = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "yesterday": today - timedelta(days=1),
    }
    for phrase, value in single_dates.items():
        if re.search(rf"\b{phrase}\b", lowered):
            normalized[phrase] = _date_range(value, value + timedelta(days=1), timezone)

    if "next week" in lowered:
        start = today + timedelta(days=(7 - today.weekday()))
        normalized["next week"] = _date_range(start, start + timedelta(days=7), timezone)
    if "last week" in lowered:
        this_monday = today - timedelta(days=today.weekday())
        normalized["last week"] = _date_range(
            this_monday - timedelta(days=7), this_monday, timezone
        )
    if "last month" in lowered:
        first_this_month = today.replace(day=1)
        last_previous_month = first_this_month - timedelta(days=1)
        first_previous_month = last_previous_month.replace(day=1)
        normalized["last month"] = _date_range(
            first_previous_month, first_this_month, timezone
        )

    weekday_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, weekday in weekday_names.items():
        phrase = f"next {name}"
        if phrase in lowered:
            days_ahead = (weekday - today.weekday()) % 7 or 7
            value = today + timedelta(days=days_ahead)
            normalized[phrase] = _date_range(value, value + timedelta(days=1), timezone)
    return normalized


def _date_range(start: date, end: date, timezone: ZoneInfo) -> dict[str, str]:
    return {
        "start": datetime.combine(start, time.min, timezone).isoformat(),
        "end": datetime.combine(end, time.min, timezone).isoformat(),
    }
