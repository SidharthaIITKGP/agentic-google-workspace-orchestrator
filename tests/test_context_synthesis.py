import asyncio
from datetime import datetime, timezone

from app.api.routes.query import _recent_context
from app.db.models import Message
from app.orchestration.synthesis import ResponseSynthesizer
from app.orchestration.compaction import compact_result_data
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


def test_synthesis_distinguishes_completed_empty_from_failed_and_skipped() -> None:
    async def exercise() -> None:
        class Provider:
            async def generate_json(self, system_prompt, payload):
                facts = {item["step_id"]: item for item in payload["execution_facts"]}
                assert facts["empty"]["completed_empty"] is True
                assert facts["failed"]["attempted"] is True
                assert facts["skipped"]["attempted"] is False
                return {"response": "No related messages or files were found."}

        response = await ResponseSynthesizer(Provider()).synthesize(
            "find related content",
            [
                StepResult(
                    step_id="empty",
                    status=ExecutionStatus.COMPLETED,
                    data={"emails": []},
                ),
                StepResult(
                    step_id="failed",
                    status=ExecutionStatus.FAILED,
                ),
                StepResult(
                    step_id="skipped",
                    status=ExecutionStatus.SKIPPED,
                ),
            ],
        )

        assert "Email search completed with no matching results" in response
        assert "failed" in response
        assert "not attempted" in response
        assert "No related messages or files were found" not in response

    asyncio.run(exercise())


def test_synthesis_preserves_drive_result_order() -> None:
    async def exercise() -> None:
        class Provider:
            async def generate_json(self, system_prompt, payload):
                names = [
                    item["name"]
                    for item in payload["execution_results"][0]["data"]["files"]
                ]
                assert names == ["newest", "middle", "oldest"]
                return {"response": ", ".join(names)}

        response = await ResponseSynthesizer(Provider()).synthesize(
            "latest Drive files",
            [
                StepResult(
                    step_id="drive",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "files": [
                            {"name": "newest", "modified_time": "2026-09-25T03:00:00Z"},
                            {"name": "middle", "modified_time": "2026-09-25T02:00:00Z"},
                            {"name": "oldest", "modified_time": "2026-09-25T01:00:00Z"},
                        ]
                    },
                )
            ],
        )
        assert response == "newest, middle, oldest"

    asyncio.run(exercise())


def test_synthesis_compaction_omits_bulky_fields_without_reordering() -> None:
    compact = compact_result_data(
        {
            "files": [
                {
                    "id": "new",
                    "name": "newest",
                    "modifiedTime": "2026-09-25T03:00:00Z",
                    "content": "large extracted body",
                    "next_page_token": "not-user-facing",
                },
                {
                    "id": "old",
                    "name": "oldest",
                    "modified_time": "2026-09-25T01:00:00Z",
                    "content": "large extracted body",
                },
            ]
        }
    )
    assert [item["name"] for item in compact["files"]] == ["newest", "oldest"]
    assert compact["files"][0]["modified_time"] == "2026-09-25T03:00:00Z"
    assert "content" not in compact["files"][0]
    assert "next_page_token" not in compact


def test_contextual_synthesis_reports_staleness_fallback_and_bounds_attendees() -> None:
    class Provider:
        async def generate_json(self, system_prompt, payload):
            raise AssertionError("contextual results should use grounded synthesis")

    response = asyncio.run(
        ResponseSynthesizer(Provider()).synthesize(
            "prepare me for my next meeting",
            [
                StepResult(
                    step_id="calendar",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "events": [
                            {
                                "title": "Project review",
                                "start": "2026-09-28T10:30:00+05:30",
                                "attendees": [
                                    f"person{index}@example.com" for index in range(12)
                                ],
                            }
                        ]
                    },
                ),
                StepResult(
                    step_id="gmail",
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "results": [
                            {
                                "service": "gmail",
                                "title": "Project notes",
                                "snippet": "A concise native match",
                            }
                        ],
                        "searched_services": ["gmail"],
                        "index_stale": True,
                        "native_fallback_recommended": True,
                        "native_fallback_performed": True,
                    },
                ),
            ],
        )
    )

    assert "Project review" in response
    assert "person4@example.com" in response
    assert "person5@example.com" not in response
    assert "and 7 more" in response
    assert "native read-only fallback was used" in response


def test_calendar_compaction_keeps_attendee_count_without_large_address_list() -> None:
    compact = compact_result_data(
        {
            "events": [
                {
                    "title": "Project review",
                    "attendees": [
                        f"person{index}@example.com" for index in range(55)
                    ],
                    "description": "large description" * 100,
                }
            ]
        }
    )

    event = compact["events"][0]
    assert len(event["attendees"]) == 5
    assert event["attendee_count"] == 55
    assert "description" not in event
