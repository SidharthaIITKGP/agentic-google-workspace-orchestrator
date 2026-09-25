import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.agents.workspace import WorkspaceSearchAgent
from app.retrieval.search import WorkspaceSearchResponse
from app.schemas.contracts import AgentResult, ExecutionStatus


def _settings():
    return SimpleNamespace(index_stale_after_minutes=15)


def _sync_state(age_minutes: int) -> dict[str, dict[str, object]]:
    return {
        "gmail": {
            "status": "completed",
            "last_successful_sync": datetime.now(timezone.utc)
            - timedelta(minutes=age_minutes),
        }
    }


def test_stale_empty_semantic_search_runs_native_read_fallback() -> None:
    async def exercise() -> None:
        class Search:
            async def search(self, **kwargs):
                return WorkspaceSearchResponse(
                    results=[],
                    duration_ms=2,
                    embedding_duration_ms=1,
                    database_duration_ms=1,
                    embedding_cache_hit=True,
                    sync_states=_sync_state(60),
                )

        class NativeGmail:
            def __init__(self) -> None:
                self.calls = []

            async def execute(self, operation, arguments):
                self.calls.append((operation, arguments))
                return AgentResult(
                    status=ExecutionStatus.COMPLETED,
                    data={
                        "emails": [
                            {
                                "id": "message-1",
                                "subject": "Distributed systems notes",
                                "preview": "Consensus experiment results",
                            }
                        ]
                    },
                    source_ids=["message-1"],
                )

        native = NativeGmail()
        agent = WorkspaceSearchAgent(
            Search(),
            uuid4(),
            _settings(),
            native_agents={"gmail": native},
        )
        result = await agent.workspace_search(
            {
                "query": {
                    "title": "University | Distributed Systems Research",
                    "description": "Consensus and fault tolerance",
                    "attendees": [],
                },
                "services": ["gmail"],
            }
        )

        assert native.calls[0][0] == "search_emails"
        assert result.data["native_fallback_recommended"] is True
        assert result.data["native_fallback_performed"] is True
        assert result.data["results"][0]["retrieval_source"] == "native_fallback"

    asyncio.run(exercise())


def test_stale_useful_semantic_results_are_kept_without_native_fallback() -> None:
    async def exercise() -> None:
        class IndexedResult:
            external_resource_id = "indexed-1"

            def as_dict(self):
                return {
                    "service": "gmail",
                    "external_resource_id": "indexed-1",
                    "title": "Relevant indexed result",
                    "score": 0.8,
                }

        class Search:
            async def search(self, **kwargs):
                return WorkspaceSearchResponse(
                    results=[IndexedResult()],
                    duration_ms=2,
                    embedding_duration_ms=1,
                    database_duration_ms=1,
                    sync_states=_sync_state(60),
                )

        class NativeGmail:
            def __init__(self) -> None:
                self.calls = 0

            async def execute(self, operation, arguments):
                self.calls += 1
                raise AssertionError("useful semantic results must not be discarded")

        native = NativeGmail()
        agent = WorkspaceSearchAgent(
            Search(),
            uuid4(),
            _settings(),
            native_agents={"gmail": native},
        )
        result = await agent.workspace_search(
            {"query": "distributed systems research", "services": ["gmail"]}
        )

        assert native.calls == 0
        assert result.data["results"][0]["title"] == "Relevant indexed result"
        assert result.data["index_stale"] is True
        assert result.data["native_fallback_performed"] is False

    asyncio.run(exercise())
