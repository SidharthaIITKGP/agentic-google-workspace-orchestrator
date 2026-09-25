from app.api.routes.query import _sanitized_approval_preview
from app.core.config import Settings


def test_frontend_origin_has_safe_local_default() -> None:
    assert Settings(_env_file=None).frontend_origin == "http://localhost:5173"


def test_approval_preview_is_allowlisted_and_bounded() -> None:
    preview = _sanitized_approval_preview(
        {
            "service": "google_calendar",
            "operation": "create_event",
            "arguments": {
                "title": "Demo meeting",
                "start": "2026-09-28T10:00:00+05:30",
                "end": "2026-09-28T10:30:00+05:30",
                "attendees": [f"person{index}@example.com" for index in range(20)],
                "create_google_meet": True,
                "description": "private long description",
                "conference_data": {"secret": "must-not-leak"},
            },
            "provider_token": "must-not-leak",
        }
    )

    assert preview is not None
    assert preview["operation"] == "create_event"
    assert len(preview["arguments"]["attendees"]) == 10
    assert "description" not in preview["arguments"]
    assert "conference_data" not in preview["arguments"]
    assert "provider_token" not in preview
