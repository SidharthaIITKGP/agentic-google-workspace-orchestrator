from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.retrieval.freshness import evaluate_service_freshness


@dataclass
class State:
    service: str
    status: str
    last_successful_sync: datetime | None


def test_freshness_is_reported_per_requested_service() -> None:
    now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    result = evaluate_service_freshness(
        [
            State("gmail", "completed", now - timedelta(minutes=2)),
            State("google_drive", "completed", now - timedelta(minutes=30)),
        ],
        {"gmail", "google_drive", "google_calendar"},
        now=now,
        stale_after=timedelta(minutes=15),
    )
    assert result["gmail"].fresh is True
    assert result["google_drive"].reason == "age_exceeded"
    assert result["google_calendar"].reason == "never_synced"


def test_naive_sync_timestamp_is_not_treated_as_fresh() -> None:
    now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    result = evaluate_service_freshness(
        [State("gmail", "completed", datetime(2026, 9, 25, 11, 59))],
        {"gmail"},
        now=now,
        stale_after=timedelta(minutes=15),
    )
    assert result["gmail"].fresh is False
    assert result["gmail"].reason == "invalid_naive_timestamp"


def test_incomplete_sync_is_stale_even_with_recent_previous_timestamp() -> None:
    now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
    result = evaluate_service_freshness(
        [State("gmail", "failed", now - timedelta(minutes=1))],
        {"gmail"},
        now=now,
        stale_after=timedelta(minutes=15),
    )
    assert result["gmail"].fresh is False
    assert result["gmail"].reason == "sync_failed"
