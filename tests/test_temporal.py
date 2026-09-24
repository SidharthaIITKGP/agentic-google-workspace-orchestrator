from datetime import datetime, timezone

from app.orchestration.temporal import normalize_temporal_expressions


def test_temporal_normalization_uses_explicit_reference() -> None:
    result = normalize_temporal_expressions(
        "Show tomorrow, next week, next Tuesday, and last month",
        datetime(2026, 9, 24, 12, tzinfo=timezone.utc),
        "UTC",
    )

    assert result["tomorrow"]["start"].startswith("2026-09-25")
    assert result["next week"]["start"].startswith("2026-09-28")
    assert result["next tuesday"]["start"].startswith("2026-09-29")
    assert result["last month"]["start"].startswith("2026-08-01")
