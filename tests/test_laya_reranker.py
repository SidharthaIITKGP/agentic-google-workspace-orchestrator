import asyncio
from types import SimpleNamespace

from app.llm.laya import LayaProviderError, LayaRelevanceDecision
from app.retrieval.laya_reranker import LayaWorkspaceReranker, _sanitized_candidate


class Provider:
    def __init__(self, probabilities=None, fail=False):
        self.probabilities = probabilities or []
        self.fail = fail
        self.candidates = None

    async def relevance(self, query, candidates):
        self.candidates = candidates
        if self.fail:
            raise LayaProviderError("timeout")
        return LayaRelevanceDecision(
            probabilities=self.probabilities,
            model="laya-test",
            latency_ms=4.0,
            input_tokens=20,
        )


def _candidates():
    return [
        {"id": "weak", "service": "gmail", "title": "Digest", "chunk_text": "general news"},
        {"id": "best", "service": "google_drive", "title": "Alpha research", "chunk_text": "experiment results"},
        {"id": "okay", "service": "gmail", "title": "Alpha update", "chunk_text": "weekly progress"},
    ]


def test_laya_reranking_improves_order_and_respects_candidate_cap() -> None:
    async def exercise() -> None:
        provider = Provider([0.1, 0.95])
        reranker = LayaWorkspaceReranker(provider, candidate_cap=2, relevance_threshold=0.5)
        outcome = await reranker.rerank("Alpha research", _candidates(), 5)
        assert [item["id"] for item in outcome.results] == ["best"]
        assert len(provider.candidates) == 2
        assert outcome.provider == "laya"
        assert outcome.input_tokens == 20

    asyncio.run(exercise())


def test_laya_failure_preserves_existing_hybrid_order() -> None:
    async def exercise() -> None:
        candidates = _candidates()
        outcome = await LayaWorkspaceReranker(
            Provider(fail=True), candidate_cap=10, relevance_threshold=0.5
        ).rerank("Alpha", candidates, 2)
        assert outcome.results == candidates[:2]
        assert outcome.fallback_used is True

    asyncio.run(exercise())


def test_laya_state_minimizes_sensitive_candidate_data() -> None:
    sanitized = _sanitized_candidate(
        {
            "service": "gmail",
            "title": "Research update",
            "chunk_text": "x" * 900,
            "oauth_token": "secret",
            "attendees": ["many@example.com"],
            "metadata": {"meeting_password": "secret"},
        }
    )
    assert set(sanitized) == {"service", "title", "snippet"}
    assert len(sanitized["snippet"]) == 500
    assert "secret" not in str(sanitized)
