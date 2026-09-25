import re
from dataclasses import dataclass
from typing import Any


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "documents", "emails", "find", "for", "in",
    "me", "my", "of", "on", "related", "research", "the", "to", "with",
}


@dataclass(frozen=True)
class RankedCandidate:
    item: Any
    score: float
    lexical_coverage: float


def select_relevant_candidates(
    candidates: list[Any],
    query: str,
    *,
    top_k: int,
    requested_services: set[str] | None = None,
    minimum_score: float = 0.30,
) -> list[Any]:
    """Apply explainable lexical/vector calibration and stable thread deduplication."""
    query_terms = _meaningful_tokens(query)
    ranked: list[RankedCandidate] = []
    for candidate in candidates:
        service = str(_value(candidate, "service") or "")
        if requested_services and service not in requested_services:
            continue
        title = str(_value(candidate, "title") or "")
        snippet = str(
            _value(candidate, "snippet")
            or _value(candidate, "chunk_text")
            or _value(candidate, "text")
            or ""
        )
        candidate_terms = set(_TOKEN_PATTERN.findall(f"{title} {snippet}".lower()))
        coverage = (
            len(query_terms & candidate_terms) / len(query_terms)
            if query_terms
            else 0.0
        )
        base_score = _bounded_score(_value(candidate, "score"))
        title_coverage = (
            len(query_terms & set(_TOKEN_PATTERN.findall(title.lower()))) / len(query_terms)
            if query_terms
            else 0.0
        )
        calibrated = 0.60 * base_score + 0.30 * coverage + 0.10 * title_coverage
        if calibrated >= minimum_score and (coverage > 0 or base_score >= 0.60):
            ranked.append(RankedCandidate(candidate, calibrated, coverage))

    ranked.sort(key=lambda result: result.score, reverse=True)
    selected: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for ranked_candidate in ranked:
        candidate = ranked_candidate.item
        key = _deduplication_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) == top_k:
            break
    return selected


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN_PATTERN.findall(value.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def _bounded_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _value(candidate: Any, name: str) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name)
    return getattr(candidate, name, None)


def _deduplication_key(candidate: Any) -> tuple[str, str]:
    service = str(_value(candidate, "service") or "")
    metadata = _value(candidate, "metadata") or _value(candidate, "resource_metadata")
    if service == "gmail" and isinstance(metadata, dict):
        thread_id = metadata.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return service, f"thread:{thread_id}"
    external_id = _value(candidate, "external_resource_id") or _value(candidate, "id")
    if isinstance(external_id, str) and external_id:
        return service, external_id
    title = " ".join(str(_value(candidate, "title") or "").lower().split())
    return service, title
