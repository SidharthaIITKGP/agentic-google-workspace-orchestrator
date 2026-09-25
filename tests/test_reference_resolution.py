import pytest

from app.orchestration.executor import ReferenceResolutionError, _resolve_references
from app.schemas.contracts import ExecutionStatus, StepResult


def _calendar_results(events: list[dict[str, object]]) -> dict[str, StepResult]:
    return {
        "calendar": StepResult(
            step_id="calendar",
            status=ExecutionStatus.COMPLETED,
            data={"events": events},
        )
    }


@pytest.mark.parametrize("selector", [0, "0", "first", "next"])
def test_resolves_first_calendar_event_title(selector: int | str) -> None:
    resolved = _resolve_references(
        {"$step": "calendar", "path": ["events", selector, "title"]},
        _calendar_results(
            [
                {
                    "title": "Meeting with Soham",
                    "attendees": ["soham@example.com"],
                }
            ]
        ),
    )
    assert resolved == "Meeting with Soham"


def test_resolves_calendar_attendees_for_dependent_search() -> None:
    resolved = _resolve_references(
        {"$step": "calendar", "path": ["events", 0, "attendees"]},
        _calendar_results(
            [
                {
                    "title": "Meeting with Soham",
                    "attendees": ["soham@example.com"],
                }
            ]
        ),
    )
    assert resolved == ["soham@example.com"]


def test_calendar_result_resolves_for_parallel_gmail_and_drive_arguments() -> None:
    results = _calendar_results(
        [
            {
                "title": "Meeting with Soham",
                "attendees": ["soham@example.com"],
            }
        ]
    )
    gmail_arguments = _resolve_references(
        {
            "keywords": {"$step": "calendar", "path": ["events", 0, "title"]},
            "sender": {
                "$step": "calendar",
                "path": ["events", 0, "attendees", 0],
            },
        },
        results,
    )
    drive_arguments = _resolve_references(
        {
            "filename": {"$step": "calendar", "path": ["events", 0, "title"]}
        },
        results,
    )
    assert gmail_arguments == {
        "keywords": "Meeting with Soham",
        "sender": "soham@example.com",
    }
    assert drive_arguments == {"filename": "Meeting with Soham"}


def test_empty_calendar_event_list_is_an_explicit_missing_element() -> None:
    with pytest.raises(ReferenceResolutionError) as exc_info:
        _resolve_references(
            {"$step": "calendar", "path": ["events", 0, "title"]},
            _calendar_results([]),
        )
    assert exc_info.value.code == "reference_element_missing"
    assert exc_info.value.path == ["events", 0]


def test_missing_calendar_field_is_not_fabricated() -> None:
    with pytest.raises(ReferenceResolutionError) as exc_info:
        _resolve_references(
            {"$step": "calendar", "path": ["events", 0, "title"]},
            _calendar_results([{"attendees": []}]),
        )
    assert exc_info.value.code == "reference_field_missing"
