from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.llm.laya import LayaDecisionProviderProtocol, LayaProviderError


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankOutcome:
    results: list[Any]
    provider: str
    latency_ms: float = 0.0
    fallback_used: bool = False
    model: str | None = None
    input_tokens: int | None = None


class CandidateReranker(Protocol):
    @property
    def candidate_cap(self) -> int: ...

    async def rerank(
        self, query: str, candidates: list[Any], top_k: int
    ) -> RerankOutcome: ...


class LayaWorkspaceReranker:
    def __init__(
        self,
        provider: LayaDecisionProviderProtocol,
        *,
        candidate_cap: int = 10,
        relevance_threshold: float = 0.55,
    ) -> None:
        self._provider = provider
        self._candidate_cap = candidate_cap
        self._threshold = relevance_threshold

    @property
    def candidate_cap(self) -> int:
        return self._candidate_cap

    async def rerank(
        self, query: str, candidates: list[Any], top_k: int
    ) -> RerankOutcome:
        bounded = candidates[: self._candidate_cap]
        if not bounded:
            return RerankOutcome([], "laya")
        try:
            decision = await self._provider.relevance(
                query, [_sanitized_candidate(candidate) for candidate in bounded]
            )
            if len(decision.probabilities) != len(bounded):
                raise LayaProviderError("Laya result count did not match candidates")
        except LayaProviderError:
            logger.warning("Laya reranking failed; preserving hybrid ranking")
            return RerankOutcome(
                results=candidates[:top_k],
                provider="hybrid_fallback",
                fallback_used=True,
            )
        scored = [
            (candidate, probability, index)
            for index, (candidate, probability) in enumerate(
                zip(bounded, decision.probabilities, strict=True)
            )
            if probability >= self._threshold
        ]
        scored.sort(key=lambda item: (-item[1], item[2]))
        return RerankOutcome(
            results=[candidate for candidate, _, _ in scored[:top_k]],
            provider="laya",
            latency_ms=decision.latency_ms,
            model=decision.model,
            input_tokens=decision.input_tokens,
        )


def _sanitized_candidate(candidate: Any) -> dict[str, str]:
    title = _value(candidate, "title")
    snippet = _value(candidate, "snippet") or _value(candidate, "chunk_text") or _value(candidate, "text")
    return {
        "service": str(_value(candidate, "service") or "")[:40],
        "title": " ".join(str(title or "").split())[:300],
        "snippet": " ".join(str(snippet or "").split())[:500],
    }


def _value(candidate: Any, name: str) -> Any:
    return candidate.get(name) if isinstance(candidate, dict) else getattr(candidate, name, None)
