import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agents.calendar import CalendarAgent
from app.api.routes import approvals as approval_routes
from app.orchestration.planner import _canonical_arguments
from app.orchestration.registry import APPROVAL_REQUIRED_OPERATIONS
from app.orchestration.temporal import normalize_temporal_expressions
from app.schemas.contracts import ExecutionStatus, Intent, Service


START = "2026-09-25T10:00:00+05:30"
END = "2026-09-25T10:30:00+05:30"


def _intent(start: str = START) -> Intent:
    return Intent(
        intent_name="create_calendar_event",
        required_services=[Service.GOOGLE_CALENDAR],
        extracted_entities={
            "start_time": start,
            "attendee_email": "sohammondal29@gmail.com",
        },
        requires_clarification=False,
    )


def test_ten_am_tomorrow_uses_kolkata_offset() -> None:
    hints = normalize_temporal_expressions(
        "schedule a meeting at 10am tomorrow",
        datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        "Asia/Kolkata",
    )
    serialized = json.dumps(hints, default=str)

    assert "2026-09-25T10:00:00+05:30" in serialized
    assert "2026-09-25T10:00:00+00:00" not in serialized


def test_calendar_create_defaults_duration_and_detects_google_meet() -> None:
    arguments = _canonical_arguments(
        Service.GOOGLE_CALENDAR,
        "create_event",
        {
            "title": "Google Meet with Soham",
            "start": START,
            "attendees": ["sohammondal29@gmail.com"],
        },
        _intent(),
        query="Schedule a Google Meet with Soham at 10am tomorrow",
        timezone_name="Asia/Kolkata",
        default_meeting_duration_minutes=30,
    )

    assert arguments["start"] == START
    assert arguments["end"] == END
    assert arguments["timezone"] == "Asia/Kolkata"
    assert arguments["create_google_meet"] is True


def test_ordinary_event_does_not_request_google_meet() -> None:
    arguments = _canonical_arguments(
        Service.GOOGLE_CALENDAR,
        "create_event",
        {"title": "Coffee", "start": START},
        _intent(),
        query="Schedule coffee tomorrow at 10am",
        timezone_name="Asia/Kolkata",
    )

    assert arguments["create_google_meet"] is False


def test_calendar_agent_requests_and_returns_google_meet() -> None:
    captured: dict[str, object] = {}
    conference_data = {
        "entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc-defg-hij"}],
        "conferenceSolution": {"name": "Google Meet"},
    }

    class Request:
        def execute(self):
            return {
                "id": "event-1",
                "summary": "Google Meet with Soham",
                "start": {"dateTime": START, "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": END, "timeZone": "Asia/Kolkata"},
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
                "conferenceData": conference_data,
                "status": "confirmed",
            }

    class Events:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class ServiceClient:
        def events(self):
            return Events()

    class Clients:
        async def build(self, service_name: str, version: str):
            return ServiceClient()

    result = asyncio.run(
        CalendarAgent(Clients()).create_event(
            {
                "title": "Google Meet with Soham",
                "start": START,
                "end": END,
                "timezone": "Asia/Kolkata",
                "attendees": ["sohammondal29@gmail.com"],
                "create_google_meet": True,
            }
        )
    )

    assert captured["conferenceDataVersion"] == 1
    create_request = captured["body"]["conferenceData"]["createRequest"]
    assert create_request["requestId"]
    assert create_request["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert result.data["event"]["meet_url"] == "https://meet.google.com/abc-defg-hij"
    assert result.data["event"]["conference_data"] == conference_data


def test_ordinary_calendar_event_omits_conference_request() -> None:
    captured: dict[str, object] = {}

    class Request:
        def execute(self):
            return {
                "id": "event-2",
                "summary": "Coffee",
                "start": {"dateTime": START},
                "end": {"dateTime": END},
            }

    class Events:
        def insert(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class ServiceClient:
        def events(self):
            return Events()

    class Clients:
        async def build(self, service_name: str, version: str):
            return ServiceClient()

    asyncio.run(
        CalendarAgent(Clients()).create_event(
            {"title": "Coffee", "start": START, "end": END, "create_google_meet": False}
        )
    )

    assert "conferenceDataVersion" not in captured
    assert "conferenceData" not in captured["body"]


def test_calendar_create_remains_approval_gated() -> None:
    assert (Service.GOOGLE_CALENDAR, "create_event") in APPROVAL_REQUIRED_OPERATIONS


def test_approval_executes_stored_action_exactly_once(monkeypatch) -> None:
    user_id = uuid4()
    approval_id = uuid4()
    execution_id = uuid4()
    stored_arguments = {
        "title": "Google Meet with Soham",
        "start": START,
        "end": END,
        "timezone": "Asia/Kolkata",
        "attendees": ["sohammondal29@gmail.com"],
        "create_google_meet": True,
    }
    approval = SimpleNamespace(
        id=approval_id,
        user_id=user_id,
        execution_id=execution_id,
        step_id="create-meeting",
        status=ExecutionStatus.AWAITING_APPROVAL.value,
        proposed_action={
            "service": Service.GOOGLE_CALENDAR.value,
            "operation": "create_event",
            "arguments": stored_arguments,
        },
    )
    step = SimpleNamespace(status=None, result=None, error_details=None)
    executed: list[dict] = []

    async def pending(session, requested_id, requested_user_id):
        if approval.status != ExecutionStatus.AWAITING_APPROVAL.value:
            raise HTTPException(status_code=409, detail="Approval is no longer pending")
        return approval

    async def execution_step(session, selected_approval):
        return step

    async def refresh(session, selected_execution_id):
        return None

    class Registry:
        def validate_operation(self, service, operation):
            return None

        async def execute(self, service, operation, arguments):
            executed.append(arguments)
            return SimpleNamespace(
                status=ExecutionStatus.COMPLETED,
                data={"event": {"id": "event-1"}},
                error=None,
            )

    class Session:
        def add(self, value):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(approval_routes, "_pending_approval", pending)
    monkeypatch.setattr(approval_routes, "_execution_step", execution_step)
    monkeypatch.setattr(approval_routes, "_refresh_execution_status", refresh)
    monkeypatch.setattr(approval_routes, "build_agent_registry", lambda *args: Registry())

    session = Session()
    asyncio.run(approval_routes.approve_action(approval_id, user_id, session))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(approval_routes.approve_action(approval_id, user_id, session))

    assert exc_info.value.status_code == 409
    assert executed == [stored_arguments]
