from app.orchestration.operation_specs import validate_operation_arguments
from app.orchestration.planner import _canonical_arguments
from app.orchestration.registry import APPROVAL_REQUIRED_OPERATIONS
from app.schemas.contracts import ExecutionPlan, ExecutionStep, Intent, Service


def test_workspace_search_filters_validate() -> None:
    validate_operation_arguments(
        Service.WORKSPACE,
        "workspace_search",
        {
            "query": "Acme proposal",
            "services": ["gmail", "google_calendar", "google_drive"],
            "top_k": 5,
            "sender": "person@example.com",
            "attendee": "person@example.com",
            "mime_type": "application/pdf",
            "date_from": "2026-01-01T00:00:00+00:00",
            "date_to": "2027-01-01T00:00:00+00:00",
        },
    )


def test_contextual_plan_supports_independent_multi_service_retrieval() -> None:
    plan = ExecutionPlan(
        steps=[
            ExecutionStep(
                step_id="meeting",
                service=Service.GOOGLE_CALENDAR,
                operation="search_events",
                arguments={},
            ),
            ExecutionStep(
                step_id="context",
                service=Service.WORKSPACE,
                operation="workspace_search",
                arguments={
                    "query": "Acme Corp",
                    "services": ["gmail", "google_drive"],
                    "top_k": 5,
                },
            ),
        ]
    )
    assert all(not step.depends_on for step in plan.steps)


def test_workspace_temporal_filters_are_mapped_from_intent() -> None:
    intent = Intent(
        intent_name="prepare_for_meeting",
        required_services=[Service.GOOGLE_CALENDAR, Service.GMAIL, Service.GOOGLE_DRIVE],
        extracted_entities={
            "date_range": {
                "start": "2026-09-25T00:00:00+05:30",
                "end": "2026-09-26T00:00:00+05:30",
            }
        },
    )
    arguments = _canonical_arguments(
        Service.WORKSPACE,
        "workspace_search",
        {"query": "Acme"},
        intent,
        query="Prepare me for tomorrow's meeting with Acme",
    )
    assert arguments["date_from"] == "2026-09-25T00:00:00+05:30"
    assert arguments["date_to"] == "2026-09-26T00:00:00+05:30"


def test_no_write_operation_bypasses_approval() -> None:
    expected = {
        (Service.GMAIL, "send_email"),
        (Service.GMAIL, "update_labels"),
        (Service.GOOGLE_CALENDAR, "create_event"),
        (Service.GOOGLE_CALENDAR, "update_event"),
        (Service.GOOGLE_CALENDAR, "delete_event"),
        (Service.GOOGLE_DRIVE, "share_file"),
        (Service.GOOGLE_DRIVE, "create_folder"),
        (Service.GOOGLE_DRIVE, "move_file"),
    }
    assert expected <= APPROVAL_REQUIRED_OPERATIONS
    assert (Service.WORKSPACE, "workspace_search") not in APPROVAL_REQUIRED_OPERATIONS
