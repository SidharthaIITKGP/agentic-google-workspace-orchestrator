import asyncio
from datetime import datetime, timezone

from app.agents.calendar import CalendarAgent
from app.agents.workspace import _contextual_query
from app.orchestration.operation_specs import OPERATION_SPECIFICATIONS
from app.orchestration.planner import _apply_intent_constraints, _canonical_arguments
from app.orchestration.synthesis import ResponseSynthesizer
from app.schemas.contracts import (
    ExecutionPlan,
    ExecutionStatus,
    ExecutionStep,
    Intent,
    Service,
    StepResult,
)


QUERY = (
    "Find my upcoming Distributed Quantum Computing Research meeting, "
    "identify its title and attendees, then find related emails and Drive documents"
)
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _intent() -> Intent:
    return Intent(
        intent_name="prepare_for_meeting",
        required_services=[
            Service.GOOGLE_CALENDAR,
            Service.GMAIL,
            Service.GOOGLE_DRIVE,
        ],
        extracted_entities={"event_selector": "upcoming"},
    )


def test_upcoming_calendar_arguments_start_at_user_local_now() -> None:
    arguments = _canonical_arguments(
        Service.GOOGLE_CALENDAR,
        "search_events",
        {"keywords": "Distributed Quantum Computing Research"},
        _intent(),
        query=QUERY,
        timezone_name="Asia/Kolkata",
        reference_time=NOW,
    )

    assert arguments["time_min"] == "2026-09-25T17:30:00+05:30"
    assert arguments["max_results"] == 1


def test_calendar_agent_excludes_history_and_selects_nearest_future_event() -> None:
    captured: dict[str, object] = {}

    class Request:
        def execute(self):
            return {
                "items": [
                    {
                        "id": "historical",
                        "summary": "Distributed Quantum Computing Research",
                        "start": {"dateTime": "2026-05-04T10:30:00+05:30"},
                    },
                    {
                        "id": "later",
                        "summary": "Distributed Quantum Computing Research",
                        "start": {"dateTime": "2026-10-05T10:30:00+05:30"},
                    },
                    {
                        "id": "nearest",
                        "summary": "Distributed Quantum Computing Research",
                        "start": {"dateTime": "2026-09-28T10:30:00+05:30"},
                    },
                ]
            }

    class Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return Request()

    class Service:
        def events(self):
            return Events()

    class Clients:
        async def build(self, service_name: str, version: str):
            return Service()

    result = asyncio.run(
        CalendarAgent(Clients()).search_events(
            {
                "time_min": "2026-09-25T17:30:00+05:30",
                "keywords": "Distributed Quantum Computing Research",
                "max_results": 1,
            }
        )
    )

    assert captured["timeMin"] == "2026-09-25T17:30:00+05:30"
    assert captured["singleEvents"] is True
    assert captured["orderBy"] == "startTime"
    assert [event["id"] for event in result.data["events"]] == ["nearest"]


def test_dependent_related_searches_are_routed_to_filtered_workspace_steps() -> None:
    native_plan = ExecutionPlan(
        steps=[
            ExecutionStep(
                step_id="calendar",
                service=Service.GOOGLE_CALENDAR,
                operation="search_events",
                arguments={"keywords": "Distributed Quantum Computing Research"},
            ),
            ExecutionStep(
                step_id="gmail",
                service=Service.GMAIL,
                operation="search_emails",
                arguments={
                    "keywords": {
                        "$step": "calendar",
                        "path": ["events", 0, "title"],
                    }
                },
                depends_on=["calendar"],
            ),
            ExecutionStep(
                step_id="drive",
                service=Service.GOOGLE_DRIVE,
                operation="search_files",
                arguments={
                    "filename": {
                        "$step": "calendar",
                        "path": ["events", 0, "title"],
                    }
                },
                depends_on=["calendar"],
            ),
        ]
    )

    plan = _apply_intent_constraints(
        native_plan,
        _intent(),
        query=QUERY,
        timezone_name="Asia/Kolkata",
        reference_time=NOW,
    )
    dependent = plan.steps[1:]

    assert all(step.service == Service.WORKSPACE for step in dependent)
    assert all(step.operation == "workspace_search" for step in dependent)
    assert all(step.depends_on == ["calendar"] for step in dependent)
    assert {tuple(step.arguments["services"]) for step in dependent} == {
        ("gmail",),
        ("google_drive",),
    }
    assert all(
        step.arguments["query"]
        == {"$step": "calendar", "path": ["events", 0]}
        for step in dependent
    )


def test_prepare_for_meeting_adds_parallel_indexed_context_searches() -> None:
    calendar_only = ExecutionPlan(
        steps=[
            ExecutionStep(
                step_id="calendar",
                service=Service.GOOGLE_CALENDAR,
                operation="search_events",
            )
        ]
    )

    plan = _apply_intent_constraints(
        calendar_only,
        _intent(),
        query="Prepare me for my next meeting",
        timezone_name="Asia/Kolkata",
        reference_time=NOW,
    )
    searches = [step for step in plan.steps if step.service == Service.WORKSPACE]

    assert len(searches) == 2
    assert {tuple(step.arguments["services"]) for step in searches} == {
        ("gmail",),
        ("google_drive",),
    }
    assert all(step.depends_on == ["calendar"] for step in searches)


def test_event_context_query_is_compact_and_limits_attendees() -> None:
    query = _contextual_query(
        {
            "title": "Project Alpha review",
            "description": "Launch readiness and risk review",
            "attendees": [f"person{index}@example.com" for index in range(20)],
        }
    )

    assert "Project Alpha review" in query
    assert "Launch readiness and risk review" in query
    assert "person2@example.com" in query
    assert "person3@example.com" not in query


def test_context_query_removes_links_credentials_and_boilerplate() -> None:
    query = _contextual_query(
        {
            "title": "University Lab | Distributed Systems Research",
            "description": (
                "Discuss fault tolerance and consensus.\n"
                "QML benchmarking and experimental design.\n"
                "Join the meeting: https://meet.google.com/example\n"
                "Passcode: 123456\n"
                "Confidentiality disclaimer: do not distribute.\n"
                "Best regards, Events Team"
            ),
            "attendees": [f"person{index}@example.com" for index in range(55)],
        }
    )

    assert "University Lab" in query
    assert "Distributed Systems Research" in query
    assert "fault tolerance and consensus" in query
    assert "QML benchmarking" in query
    assert "https://" not in query
    assert "Passcode" not in query
    assert "disclaimer" not in query
    assert "person3@example.com" not in query
    assert len(query) <= 700


def test_native_search_operations_remain_available_for_exact_or_fallback_use() -> None:
    assert "search_emails" in OPERATION_SPECIFICATIONS[Service.GMAIL]
    assert "search_files" in OPERATION_SPECIFICATIONS[Service.GOOGLE_DRIVE]


def test_generic_synthesis_response_is_replaced_with_grounded_context() -> None:
    class Provider:
        async def generate_json(self, system_prompt, payload):
            return {
                "response": "Completed 3 step(s) using the available service results."
            }

    response = asyncio.run(
        ResponseSynthesizer(Provider()).synthesize(
            QUERY,
            [
                StepResult(
                    step_id="calendar",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "events": [
                            {
                                "title": "Distributed Quantum Computing Research",
                                "start": "2026-09-28T10:30:00+05:30",
                                "attendees": ["researcher@example.com"],
                            }
                        ]
                    },
                ),
                StepResult(
                    step_id="gmail",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "results": [{"service": "gmail", "title": "Quantum notes"}],
                        "searched_services": ["gmail"],
                    },
                ),
                StepResult(
                    step_id="drive",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "results": [],
                        "searched_services": ["google_drive"],
                    },
                ),
            ],
        )
    )

    assert "2026-09-28T10:30:00+05:30" in response
    assert "Quantum notes" in response
    assert "Indexed Drive search completed with no sufficiently relevant matches" in response
    assert "Completed 3 step(s)" not in response
