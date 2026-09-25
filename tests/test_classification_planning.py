import asyncio
from datetime import datetime, timezone

import pytest

from app.llm.provider import LLMProviderError
from app.orchestration.classifier import IntentClassifier
from app.orchestration.operation_specs import validate_operation_arguments
from app.orchestration.planner import QueryPlanner
from app.orchestration.registry import AgentRegistry, UnknownOperationError
from app.schemas.contracts import ExecutionPlan, Intent, Service


class FakeProvider:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.payload: dict[str, object] | None = None

    async def generate_json(self, system_prompt, payload):
        self.payload = payload
        return self.response


def test_classifier_builds_existing_intent_schema_with_context() -> None:
    async def exercise() -> None:
        provider = FakeProvider(
            {
                "intent_name": "find_budget_email",
                "required_services": ["gmail"],
                "extracted_entities": {"sender": "sarah@company.com"},
                "requires_clarification": False,
                "clarification_question": None,
            }
        )
        intent = await IntentClassifier(provider).classify(
            "Find that budget email",
            [{"role": "user", "content": "Sarah sent the budget"}],
            datetime(2026, 9, 24, tzinfo=timezone.utc),
            "UTC",
        )

        assert intent.required_services == [Service.GMAIL]
        assert provider.payload["recent_context"]

    asyncio.run(exercise())


def test_planner_rejects_unknown_operation() -> None:
    class Registry:
        def prompt_catalog(self):
            return {"gmail": ["search_emails"]}

        def validate_plan(self, plan):
            raise ValueError("unknown")

    async def exercise() -> None:
        provider = FakeProvider(
            {
                "steps": [
                    {
                        "step_id": "invented",
                        "service": "gmail",
                        "operation": "invent_operation",
                        "arguments": {},
                        "depends_on": [],
                    }
                ]
            }
        )
        intent = await IntentClassifier(
            FakeProvider(
                {
                    "intent_name": "test",
                    "required_services": ["gmail"],
                    "extracted_entities": {},
                    "requires_clarification": False,
                    "clarification_question": None,
                }
            )
        ).classify("test", [], datetime.now(timezone.utc), "UTC")
        with pytest.raises(LLMProviderError):
            await QueryPlanner(provider, Registry()).create_plan("test", intent)

    asyncio.run(exercise())


def test_registry_rejects_unknown_operation_deterministically() -> None:
    class Agent:
        supported_operations = {"known"}

        async def execute(self, operation, arguments):
            raise AssertionError("not called")

    registry = AgentRegistry(Agent(), Agent(), Agent())

    with pytest.raises(UnknownOperationError):
        registry.validate_operation(Service.GMAIL, "invented")


def test_classifier_repairs_one_invalid_structured_response() -> None:
    class SequencedProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_json(self, system_prompt, payload):
            self.calls += 1
            if self.calls == 1:
                return {"intent_name": "missing-required-fields"}
            assert "previous response" in system_prompt.lower()
            return {
                "intent_name": "search_workspace",
                "required_services": ["gmail", "google_drive"],
                "extracted_entities": {"keywords": "quantum computing"},
                "requires_clarification": False,
                "clarification_question": None,
            }

    async def exercise() -> None:
        provider = SequencedProvider()
        intent = await IntentClassifier(provider).classify(
            "Find emails and Drive documents about quantum computing",
            [],
            datetime(2026, 9, 24, tzinfo=timezone.utc),
            "Asia/Kolkata",
        )
        assert intent.required_services == [Service.GMAIL, Service.GOOGLE_DRIVE]
        assert provider.calls == 2

    asyncio.run(exercise())


def test_planner_repairs_one_invalid_plan_before_execution() -> None:
    class SequencedProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def generate_json(self, system_prompt, payload):
            self.calls += 1
            if self.calls == 1:
                return {"steps": [{"not": "a valid step"}]}
            assert "previous response" in system_prompt.lower()
            return {
                "steps": [
                    {
                        "step_id": "search-email",
                        "service": "gmail",
                        "operation": "search_emails",
                        "arguments": {"keywords": "quantum computing"},
                        "depends_on": [],
                    }
                ]
            }

    class Registry:
        def prompt_catalog(self):
            return {"gmail": {"search_emails": {}}}

        def validate_plan(self, plan):
            return None

    async def exercise() -> None:
        provider = SequencedProvider()
        plan = await QueryPlanner(provider, Registry()).create_plan(
            "Find emails about quantum computing",
            Intent(
                intent_name="search_email",
                required_services=[Service.GMAIL],
                extracted_entities={"keywords": "quantum computing"},
                requires_clarification=False,
            ),
        )
        assert plan.steps[0].operation == "search_emails"
        assert provider.calls == 2

    asyncio.run(exercise())


def test_plan_validation_allows_prior_step_output_references() -> None:
    class Agent:
        def __init__(self, operations: set[str]) -> None:
            self.supported_operations = operations

        async def execute(self, operation, arguments):
            raise AssertionError("not called during plan validation")

    registry = AgentRegistry(
        Agent({"search_emails"}),
        Agent({"search_events"}),
        Agent({"search_files"}),
    )
    plan = ExecutionPlan.model_validate(
        {
            "steps": [
                {
                    "step_id": "next-meeting",
                    "service": "google_calendar",
                    "operation": "search_events",
                    "arguments": {"max_results": 1},
                    "depends_on": [],
                },
                {
                    "step_id": "related-email",
                    "service": "gmail",
                    "operation": "search_emails",
                    "arguments": {
                        "keywords": {
                            "$step": "next-meeting",
                            "path": ["events", 0, "title"],
                        }
                    },
                    "depends_on": ["next-meeting"],
                },
                {
                    "step_id": "related-drive",
                    "service": "google_drive",
                    "operation": "search_files",
                    "arguments": {
                        "filename": {
                            "$step": "next-meeting",
                            "path": ["events", 0, "title"],
                        }
                    },
                    "depends_on": ["next-meeting"],
                },
            ]
        }
    )

    registry.validate_plan(plan)
    assert plan.steps[1].depends_on == ["next-meeting"]
    assert plan.steps[2].depends_on == ["next-meeting"]

    with pytest.raises(ValueError):
        validate_operation_arguments(
            Service.GMAIL,
            "search_emails",
            plan.steps[1].arguments,
        )
