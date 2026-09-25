import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def normalize_temporal_expressions(
    text: str,
    reference: datetime,
    timezone_name: str,
) -> dict[str, dict[str, str]]:
    timezone = ZoneInfo(timezone_name)
    today = reference.astimezone(timezone).date()
    normalized: dict[str, dict[str, str]] = {}
    lowered = text.lower()
    explicit_time = _extract_time(lowered)

    single_dates = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "yesterday": today - timedelta(days=1),
    }
    for phrase, value in single_dates.items():
        if re.search(rf"\b{phrase}\b", lowered):
            normalized[phrase] = _temporal_value(
                value, timezone, explicit_time
            )

    if "next week" in lowered:
        start = today + timedelta(days=7 - today.weekday())
        normalized["next week"] = _date_range(
            start, start + timedelta(days=7), timezone
        )
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
            normalized[phrase] = _temporal_value(
                today + timedelta(days=days_ahead), timezone, explicit_time
            )
    return normalized


def _extract_time(text: str) -> time | None:
    match = re.search(
        r"\b(?P<hour>1[0-2]|0?[1-9])(?:[.:](?P<minute>[0-5]\d))?\s*"
        r"(?P<period>[ap])\.?m\.?\b",
        text,
    )
    if match is None:
        return None

    hour = int(match.group("hour")) % 12
    if match.group("period") == "p":
        hour += 12
    return time(hour=hour, minute=int(match.group("minute") or 0))


def _temporal_value(
    value: date,
    timezone: ZoneInfo,
    explicit_time: time | None,
) -> dict[str, str]:
    if explicit_time is not None:
        return {
            "start": datetime.combine(value, explicit_time, timezone).isoformat()
        }
    return _date_range(value, value + timedelta(days=1), timezone)


def _date_range(start: date, end: date, timezone: ZoneInfo) -> dict[str, str]:
    return {
        "start": datetime.combine(start, time.min, timezone).isoformat(),
        "end": datetime.combine(end, time.min, timezone).isoformat(),
    }
