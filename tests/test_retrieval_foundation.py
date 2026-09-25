import asyncio
import math
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from app.retrieval.chunking import chunk_text
from app.retrieval.embeddings import SentenceTransformerEmbeddingProvider
from app.retrieval.indexer import WorkspaceIndexer
from app.retrieval.normalization import NormalizedWorkspaceItem
from app.retrieval.search import HybridWorkspaceSearch, WorkspaceSearchFilters


class FakeVector:
    def __init__(self, values):
        self.values = values

    def astype(self, target):
        return self

    def tolist(self):
        return self.values


def test_embedding_dimension_and_normalization() -> None:
    provider = SentenceTransformerEmbeddingProvider("test", dimensions=384)
    vector = [1 / math.sqrt(384)] * 384
    provider._model = SimpleNamespace(
        encode=lambda *args, **kwargs: [FakeVector(vector)]
    )

    result = provider.embed_text("hello")

    assert len(result) == 384
    assert math.isclose(sum(value * value for value in result), 1.0, rel_tol=1e-6)


def test_chunking_is_deterministic_and_overlapping() -> None:
    text = " ".join(f"token-{index}" for index in range(400))

    first = chunk_text(text, target_size=800, overlap=100)
    second = chunk_text(text, target_size=800, overlap=100)

    assert first == second
    assert len(first) > 1
    assert all(600 <= len(chunk) <= 800 for chunk in first[:-1])
    assert chunk_text("small object") == ["small object"]


def test_idempotent_upsert_replaces_stale_chunks() -> None:
    async def exercise() -> None:
        item_id = uuid4()

        class Session:
            def __init__(self):
                self.deleted = 0
                self.added_batches = []

            async def scalar(self, statement):
                return item_id

            async def execute(self, statement):
                self.deleted += 1

            def add_all(self, values):
                self.added_batches.append(list(values))

            async def flush(self):
                return None

        class Embeddings:
            dimensions = 384

            def embed_texts(self, texts):
                return [[0.0] * 384 for _ in texts]

        session = Session()
        indexer = WorkspaceIndexer(session, Embeddings())
        item = NormalizedWorkspaceItem("gmail", "message-1", "Subject", "body " * 500)

        user_id = uuid4()
        first_id = await indexer.index_item(user_id, item)
        second_id = await indexer.index_item(user_id, item)

        assert first_id == second_id == item_id
        assert session.deleted == 2
        assert len(session.added_batches) == 2
        assert all(batch[0].chunk_index == 0 for batch in session.added_batches)

    asyncio.run(exercise())


def test_search_query_is_tenant_scoped_filtered_and_top_k_bounded() -> None:
    async def exercise() -> None:
        user_id = uuid4()

        class Result:
            def all(self):
                return []

        class Session:
            async def execute(self, statement):
                compiled = statement.compile(dialect=postgresql.dialect())
                values = list(compiled.params.values())
                assert values.count(user_id) >= 2
                sql = str(compiled)
                assert "metadata" in sql
                assert "LIMIT" in sql
                return Result()

        class Embeddings:
            dimensions = 384

            def embed_text(self, text):
                return [0.0] * 384

        search = HybridWorkspaceSearch(Session(), Embeddings())
        response = await search.search(
            user_id,
            "proposal",
            top_k=5,
            filters=WorkspaceSearchFilters(
                services=["gmail", "google_calendar", "google_drive"],
                sender="person@example.com",
                date_from="2026-01-01T00:00:00+00:00",
                date_to="2027-01-01T00:00:00+00:00",
                mime_type="application/pdf",
                attendee="person@example.com",
            ),
        )
        assert response.results == []
        assert response.duration_ms >= 0

    asyncio.run(exercise())


def test_embedding_cache_key_is_tenant_isolated() -> None:
    async def exercise() -> None:
        keys: list[str] = []

        class Cache:
            async def get_json(self, key):
                keys.append(key)
                return None

            async def set_json(self, key, value, ttl_seconds):
                keys.append(key)

        class Embeddings:
            dimensions = 384

            def embed_text(self, text):
                return [0.0] * 384

        search = HybridWorkspaceSearch(None, Embeddings(), Cache())
        first_user = uuid4()
        second_user = uuid4()
        await search._query_embedding(first_user, "same query")
        await search._query_embedding(second_user, "same query")

        first_keys = [key for key in keys if str(first_user) in key]
        second_keys = [key for key in keys if str(second_user) in key]
        assert first_keys
        assert second_keys
        assert set(first_keys).isdisjoint(second_keys)

    asyncio.run(exercise())
