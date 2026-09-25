import asyncio
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.retrieval.embeddings import (
    SentenceTransformerEmbeddingProvider,
    get_embedding_provider,
)
from app.retrieval.search import HybridWorkspaceSearch, WorkspaceSearchFilters


def test_embedding_provider_is_reused_per_process() -> None:
    first = get_embedding_provider("sentence-transformers/all-MiniLM-L6-v2", 384)
    second = get_embedding_provider("sentence-transformers/all-MiniLM-L6-v2", 384)
    assert first is second


def test_simultaneous_model_access_loads_sentence_transformer_once(monkeypatch) -> None:
    load_count = 0

    def load_model(model_name, device):
        nonlocal load_count
        load_count += 1
        time.sleep(0.01)
        return object()

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=load_model),
    )
    provider = SentenceTransformerEmbeddingProvider("test-model", 384)

    async def exercise() -> None:
        await asyncio.gather(
            asyncio.to_thread(provider.warmup),
            asyncio.to_thread(provider.warmup),
        )

    asyncio.run(exercise())
    assert load_count == 1


def test_identical_query_embedding_is_single_flight_and_cached() -> None:
    async def exercise() -> None:
        class Cache:
            def __init__(self) -> None:
                self.values = {}

            async def get_json(self, key):
                return self.values.get(key)

            async def set_json(self, key, value, ttl_seconds):
                self.values[key] = value

        class Embeddings:
            dimensions = 384
            model_name = "test-model-v1"

            def __init__(self) -> None:
                self.calls = 0

            def embed_text(self, text):
                self.calls += 1
                time.sleep(0.01)
                return [0.0] * 384

        embeddings = Embeddings()
        search = HybridWorkspaceSearch(None, embeddings, Cache())
        user_id = uuid4()
        first, second = await asyncio.gather(
            search._query_embedding_with_metadata(user_id, " Project   Alpha "),
            search._query_embedding_with_metadata(user_id, "project alpha"),
        )

        assert embeddings.calls == 1
        assert first[0] == second[0]
        assert {first[1], second[1]} == {False, True}

    asyncio.run(exercise())


def test_service_filters_do_not_recompute_same_query_embedding() -> None:
    async def exercise() -> None:
        class Result:
            def all(self):
                return []

        class Session:
            async def execute(self, statement):
                statement.compile(dialect=postgresql.dialect())
                return Result()

        class Embeddings:
            dimensions = 384
            model_name = "filter-independent-model"

            def __init__(self) -> None:
                self.calls = 0

            def embed_text(self, text):
                self.calls += 1
                time.sleep(0.01)
                return [0.0] * 384

        embeddings = Embeddings()
        gmail_search = HybridWorkspaceSearch(Session(), embeddings)
        drive_search = HybridWorkspaceSearch(Session(), embeddings)
        user_id = uuid4()
        gmail, drive = await asyncio.gather(
            gmail_search.search(
                user_id,
                "distributed systems research",
                filters=WorkspaceSearchFilters(services=["gmail"]),
            ),
            drive_search.search(
                user_id,
                "distributed systems research",
                filters=WorkspaceSearchFilters(services=["google_drive"]),
            ),
        )

        assert embeddings.calls == 1
        assert {gmail.embedding_cache_hit, drive.embedding_cache_hit} == {False, True}
        assert gmail.database_duration_ms >= 0
        assert drive.database_duration_ms >= 0

    asyncio.run(exercise())
