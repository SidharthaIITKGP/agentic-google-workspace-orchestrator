import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.db.models import Execution
from app.orchestration.classifier import IntentClassifier
from app.orchestration.executor import DAGExecutor
from app.orchestration.planner import QueryPlanner
from app.orchestration.registry import AgentRegistry
from app.schemas.contracts import (
    AgentResult,
    ExecutionPlan,
    ExecutionStatus,
    Intent,
    Service,
)


EXACT_QUERY = (
    "Find my next meeting, identify its title and attendees, "
    "then find related emails and Drive documents"
)


class Provider:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response

    async def generate_json(self, system_prompt, payload):
        return self.response


def test_contextual_read_only_query_does_not_require_clarification() -> None:
    intent = asyncio.run(
        IntentClassifier(
            Provider(
                {
                    "intent_name": "prepare_for_meeting",
                    "required_services": ["google_calendar"],
                    "extracted_entities": {"event_selector": "next"},
                    "requires_clarification": True,
                    "clarification_question": "What should related mean?",
                }
            )
        ).classify(
            EXACT_QUERY,
            [],
            datetime(2026, 9, 25, tzinfo=timezone.utc),
            "Asia/Kolkata",
        )
    )
    assert intent.requires_clarification is False
    assert intent.clarification_question is None
    assert set(intent.required_services) == {
        Service.GOOGLE_CALENDAR,
        Service.GMAIL,
        Service.GOOGLE_DRIVE,
    }


def test_prepare_for_next_meeting_uses_read_only_inference() -> None:
    intent = asyncio.run(
        IntentClassifier(
            Provider(
                {
                    "intent_name": "prepare_for_meeting",
                    "required_services": ["google_calendar"],
                    "extracted_entities": {"event_selector": "next"},
                    "requires_clarification": True,
                    "clarification_question": "What information is useful?",
                }
            )
        ).classify(
            "Prepare me for my next meeting",
            [],
            datetime(2026, 9, 25, tzinfo=timezone.utc),
            "Asia/Kolkata",
        )
    )
    assert intent.requires_clarification is False


def test_ambiguous_destructive_request_still_requires_clarification() -> None:
    intent = asyncio.run(
        IntentClassifier(
            Provider(
                {
                    "intent_name": "delete_meeting",
                    "required_services": ["google_calendar"],
                    "extracted_entities": {"person": "Soham"},
                    "requires_clarification": True,
                    "clarification_question": "Which matching meeting should be deleted?",
                }
            )
        ).classify(
            "Delete my meeting with Soham",
            [],
            datetime(2026, 9, 25, tzinfo=timezone.utc),
            "Asia/Kolkata",
        )
    )
    assert intent.requires_clarification is True
    assert intent.clarification_question is not None


class Session:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.committed = False

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class Agent:
    def __init__(self, operations: set[str], handler) -> None:
        self.supported_operations = operations
        self._handler = handler

    async def execute(self, operation, arguments):
        return await self._handler(operation, arguments)


def test_calendar_discovery_drives_parallel_gmail_and_drive_retrieval() -> None:
    async def exercise() -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        active_workspace_searches = 0
        peak_workspace_searches = 0

        async def calendar(operation, arguments):
            calls.append(("calendar", arguments))
            return AgentResult(
                status=ExecutionStatus.COMPLETED,
                data={
                    "events": [
                        {
                            "title": "Project Alpha review",
                            "description": "Discuss launch readiness",
                            "start": "2026-09-26T10:00:00+05:30",
                            "attendees": ["soham@example.com"],
                        }
                    ]
                },
            )

        async def gmail(operation, arguments):
            calls.append(("gmail", arguments))
            return AgentResult(status=ExecutionStatus.COMPLETED, data={"emails": []})

        async def drive(operation, arguments):
            calls.append(("drive", arguments))
            return AgentResult(status=ExecutionStatus.COMPLETED, data={"files": []})

        async def workspace(operation, arguments):
            nonlocal active_workspace_searches, peak_workspace_searches
            calls.append(("workspace", arguments))
            active_workspace_searches += 1
            peak_workspace_searches = max(
                peak_workspace_searches, active_workspace_searches
            )
            await asyncio.sleep(0)
            active_workspace_searches -= 1
            return AgentResult(
                status=ExecutionStatus.COMPLETED,
                data={
                    "results": [],
                    "searched_services": arguments["services"],
                },
            )

        registry = AgentRegistry(
            Agent({"search_emails"}, gmail),
            Agent({"search_events"}, calendar),
            Agent({"search_files"}, drive),
            workspace=Agent({"workspace_search"}, workspace),
        )
        plan = ExecutionPlan.model_validate(
            {
                "steps": [
                    {
                        "step_id": "calendar",
                        "service": "google_calendar",
                        "operation": "search_events",
                        "arguments": {"max_results": 1},
                        "depends_on": [],
                    },
                    {
                        "step_id": "gmail",
                        "service": "gmail",
                        "operation": "search_emails",
                        "arguments": {
                            "keywords": {
                                "$step": "calendar",
                                "path": ["events", 0, "title"],
                            },
                            "sender": {
                                "$step": "calendar",
                                "path": ["events", 0, "attendees", 0],
                            },
                        },
                        "depends_on": ["calendar"],
                    },
                    {
                        "step_id": "drive",
                        "service": "google_drive",
                        "operation": "search_files",
                        "arguments": {
                            "filename": {
                                "$step": "calendar",
                                "path": ["events", 0, "title"],
                            }
                        },
                        "depends_on": ["calendar"],
                    },
                ]
            }
        )
        session = Session()
        intent = Intent(
            intent_name="prepare_for_meeting",
            required_services=[
                Service.GOOGLE_CALENDAR,
                Service.GMAIL,
                Service.GOOGLE_DRIVE,
            ],
        )
        planned = await QueryPlanner(
            Provider(plan.model_dump(mode="json")), registry
        ).create_plan(EXACT_QUERY, intent, timezone_name="Asia/Kolkata")
        outcome = await DAGExecutor(session, registry).execute(
            user_id=uuid4(),
            conversation_id=uuid4(),
            intent=intent,
            plan=planned,
        )

        assert isinstance(session.added[0], Execution)
        assert session.committed is True
        assert calls[0][0] == "calendar"
        assert [name for name, _ in calls].count("workspace") == 2
        assert peak_workspace_searches == 2
        workspace_arguments = [
            arguments for name, arguments in calls if name == "workspace"
        ]
        assert {tuple(arguments["services"]) for arguments in workspace_arguments} == {
            ("gmail",),
            ("google_drive",),
        }
        assert all(
            arguments["query"]["title"] == "Project Alpha review"
            and arguments["query"]["description"] == "Discuss launch readiness"
            and arguments["query"]["attendees"] == ["soham@example.com"]
            for arguments in workspace_arguments
        )
        assert all(result.status == ExecutionStatus.COMPLETED for result in outcome.results)

    asyncio.run(exercise())
