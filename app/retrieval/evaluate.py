import asyncio
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from app.db.models import User
from app.db.session import async_session_factory
from app.retrieval.embeddings import embedding_provider_from_settings
from app.retrieval.indexer import WorkspaceIndexer
from app.retrieval.normalization import NormalizedWorkspaceItem
from app.retrieval.search import HybridWorkspaceSearch
from app.core.config import get_settings


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    relevant_ids: frozenset[str]


FIXTURES = [
    NormalizedWorkspaceItem("gmail", "mail-acme", "Acme proposal email", "Proposal pricing and delivery plan for Acme Corp"),
    NormalizedWorkspaceItem("google_drive", "drive-quantum", "Quantum notes", "Document about quantum computing and error correction"),
    NormalizedWorkspaceItem("google_calendar", "event-acme", "Acme planning meeting", "Meeting with Acme Corp about the proposal"),
]
CASES = [
    EvaluationCase("Acme proposal", frozenset({"mail-acme", "event-acme"})),
    EvaluationCase("quantum computing document", frozenset({"drive-quantum"})),
]


async def evaluate() -> None:
    settings = get_settings()
    embeddings = embedding_provider_from_settings(settings)
    async with async_session_factory() as session:
        owner = User(id=uuid4(), email=f"retrieval-eval-{uuid4()}@example.invalid")
        other = User(id=uuid4(), email=f"retrieval-eval-other-{uuid4()}@example.invalid")
        session.add_all([owner, other])
        await session.flush()
        indexer = WorkspaceIndexer(session, embeddings)
        for fixture in FIXTURES:
            await indexer.index_item(owner.id, fixture)
        await indexer.index_item(
            other.id,
            NormalizedWorkspaceItem("gmail", "other-secret", "Private", "Acme proposal confidential"),
        )
        search = HybridWorkspaceSearch(session, embeddings)
        precision_values: list[float] = []
        latencies: list[float] = []
        tenant_isolated = True
        started = perf_counter()
        for case in CASES:
            response = await search.search(owner.id, case.query, top_k=5)
            returned = [result.external_resource_id for result in response.results]
            precision_values.append(len(set(returned) & case.relevant_ids) / 5)
            latencies.append(response.duration_ms)
            tenant_isolated = tenant_isolated and "other-secret" not in returned
        total_ms = (perf_counter() - started) * 1000
        print(f"Precision@5: {sum(precision_values) / len(precision_values):.4f}")
        print(f"Mean retrieval latency ms: {sum(latencies) / len(latencies):.2f}")
        print(f"Evaluation duration ms: {total_ms:.2f}")
        print(f"Tenant isolation: {'PASS' if tenant_isolated else 'FAIL'}")
        await session.rollback()


if __name__ == "__main__":
    asyncio.run(evaluate())
