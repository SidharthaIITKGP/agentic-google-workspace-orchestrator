import asyncio
from datetime import datetime, timezone

from app.api.routes.query import _recent_context
from app.db.models import Message
from app.orchestration.synthesis import ResponseSynthesizer
from app.schemas.contracts import ExecutionStatus, StepResult


class Scalars:
    def __init__(self, values) -> None:
        self._values = values

    def all(self):
        return self._values


class ContextSession:
    def __init__(self, messages) -> None:
        self.messages = messages

    async def scalars(self, statement):
        return Scalars(self.messages)


def test_recent_context_is_compact_and_chronological() -> None:
    async def exercise() -> None:
        newest_first = [
            Message(role="assistant", content="newest", conversation_id=None),
            Message(role="user", content="older", conversation_id=None),
        ]
        context = await _recent_context(ContextSession(newest_first), object())
        assert context == [
            {"role": "user", "content": "older"},
            {"role": "assistant", "content": "newest"},
        ]

    asyncio.run(exercise())


def test_response_synthesis_receives_only_recorded_results() -> None:
    async def exercise() -> None:
        class Provider:
            payload = None

            async def generate_json(self, system_prompt, payload):
                self.payload = payload
                return {"response": "Found one email."}

        provider = Provider()
        result = StepResult(
            step_id="search",
            status=ExecutionStatus.COMPLETED,
            data={"emails": [{"id": "m1"}]},
        )
        response = await ResponseSynthesizer(provider).synthesize("find email", [result])

        assert response == "Found one email."
        assert provider.payload["execution_results"][0]["data"] == result.data

    asyncio.run(exercise())
