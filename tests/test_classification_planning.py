import asyncio
from datetime import datetime, timezone

import pytest

from app.llm.provider import LLMProviderError
from app.orchestration.classifier import IntentClassifier
from app.orchestration.planner import QueryPlanner
from app.orchestration.registry import AgentRegistry, UnknownOperationError
from app.schemas.contracts import Service


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
