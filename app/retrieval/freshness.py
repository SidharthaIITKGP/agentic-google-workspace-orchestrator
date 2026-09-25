from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


@dataclass(frozen=True)
class ServiceFreshness:
    service: str
    fresh: bool
    reason: str
    last_successful_sync: datetime | None


def evaluate_service_freshness(
    states: Iterable[object],
    requested_services: set[str],
    *,
    now: datetime,
    stale_after: timedelta,
) -> dict[str, ServiceFreshness]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Freshness reference time must be timezone-aware")
    normalized_now = now.astimezone(timezone.utc)
    by_service = {str(getattr(state, "service")): state for state in states}
    freshness: dict[str, ServiceFreshness] = {}
    for service in sorted(requested_services):
        state = by_service.get(service)
        if state is None:
            freshness[service] = ServiceFreshness(service, False, "never_synced", None)
            continue
        status = str(getattr(state, "status", ""))
        last_sync = getattr(state, "last_successful_sync", None)
        if status != "completed":
            freshness[service] = ServiceFreshness(
                service, False, f"sync_{status or 'incomplete'}", last_sync
            )
            continue
        if not isinstance(last_sync, datetime):
            freshness[service] = ServiceFreshness(service, False, "never_succeeded", None)
            continue
        if last_sync.tzinfo is None or last_sync.utcoffset() is None:
            freshness[service] = ServiceFreshness(
                service, False, "invalid_naive_timestamp", last_sync
            )
            continue
        age = normalized_now - last_sync.astimezone(timezone.utc)
        fresh = age <= stale_after
        freshness[service] = ServiceFreshness(
            service,
            fresh,
            "fresh" if fresh else "age_exceeded",
            last_sync,
        )
    return freshness
