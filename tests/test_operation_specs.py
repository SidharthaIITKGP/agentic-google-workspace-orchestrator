import asyncio

import pytest

from app.agents.calendar import CalendarAgent
from app.api.routes.query import _compact_results_for_synthesis
from app.orchestration.operation_specs import (
    planner_operation_catalog,
    validate_operation_arguments,
)
from app.orchestration.planner import _canonical_arguments
from app.schemas.contracts import Intent, Service


START = "2026-09-28T00:00:00+00:00"
END = "2026-10-05T00:00:00+00:00"


def _calendar_intent() -> Intent:
    return Intent(
        intent_name="calendar_query",
        required_services=[Service.GOOGLE_CALENDAR],
        extracted_entities={"date_range": {"start": START, "end": END}},
        requires_clarification=False,
    )


def test_calendar_date_range_maps_to_agent_argument_names() -> None:
    arguments = _canonical_arguments(
        Service.GOOGLE_CALENDAR,
        "search_events",
        {"date_range": {"start": START, "end": END}, "max_results": 10},
        _calendar_intent(),
    )

    assert arguments["time_min"] == START
    assert arguments["time_max"] == END
    assert "date_range" not in arguments


def test_next_week_calendar_plan_cannot_lose_date_filter() -> None:
    arguments = _canonical_arguments(
        Service.GOOGLE_CALENDAR,
        "search_events",
        {},
        _calendar_intent(),
    )

    assert arguments == {"time_min": START, "time_max": END}
    validate_operation_arguments(Service.GOOGLE_CALENDAR, "search_events", arguments)


def test_calendar_search_rejects_unsupported_arguments() -> None:
    with pytest.raises(ValueError, match="Unsupported arguments"):
        validate_operation_arguments(
            Service.GOOGLE_CALENDAR,
            "search_events",
            {"start_date": "2026-09-28", "end_date": "2026-10-05"},
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"time_min": "2026-09-28T00:00:00", "time_max": END},
        {"time_min": END, "time_max": START},
        {"max_results": 0},
        {"max_results": 251},
    ],
)
def test_calendar_search_rejects_invalid_arguments(arguments) -> None:
    with pytest.raises(ValueError):
        validate_operation_arguments(Service.GOOGLE_CALENDAR, "search_events", arguments)


def test_calendar_agent_passes_time_bounds_and_small_default() -> None:
    captured: dict[str, object] = {}

    class Request:
        def execute(self):
            return {"items": [], "nextPageToken": "next"}

    class Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class ServiceClient:
        def events(self):
            return Events()

    class Clients:
        async def build(self, service_name: str, version: str):
            assert (service_name, version) == ("calendar", "v3")
            return ServiceClient()

    result = asyncio.run(
        CalendarAgent(Clients()).search_events({"time_min": START, "time_max": END})
    )

    assert captured["timeMin"] == START
    assert captured["timeMax"] == END
    assert captured["maxResults"] == 20
    assert result.data["next_page_token"] == "next"


def test_operation_catalog_exposes_argument_specifications() -> None:
    search = planner_operation_catalog()["google_calendar"]["search_events"]

    assert search["required_arguments"] == {}
    assert set(search["optional_arguments"]) == {
        "time_min",
        "time_max",
        "keywords",
        "attendee",
        "max_results",
        "calendar_id",
    }


def test_synthesis_results_are_compact_and_bounded() -> None:
    class Result:
        def __init__(self, data):
            self.data = data

        def model_copy(self, update):
            return Result(update["data"])

    events = [
        {
            "id": str(index),
            "title": f"Event {index}",
            "start": START,
            "end": END,
            "attendees": ["person@example.com"],
            "status": "confirmed",
            "description": "x" * 1_000,
            "html_link": "https://calendar.example/event",
        }
        for index in range(30)
    ]

    compact = _compact_results_for_synthesis(
        [Result({"events": events, "next_page_token": "next"})]
    )[0].data

    assert len(compact["events"]) == 20
    assert len(compact["events"][0]["description"]) == 500
    assert "id" not in compact["events"][0]
    assert "html_link" not in compact["events"][0]
    assert compact["next_page_token"] == "next"
