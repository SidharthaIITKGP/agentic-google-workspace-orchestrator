from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from app.core.config import get_settings
from app.llm.laya import build_laya_provider
from app.llm.provider import GroqProvider
from app.orchestration.classifier import IntentClassifier
from app.orchestration.decisions import HybridDecisionEngine
from app.retrieval.laya_reranker import LayaWorkspaceReranker
from app.schemas.contracts import Intent, Service


@dataclass(frozen=True)
class RoutingCase:
    query: str
    family: str
    services: frozenset[str]
    clarify: bool


ROUTING_CASES = (
    RoutingCase("Show my latest unread emails", "gmail_read", frozenset({"gmail"}), False),
    RoutingCase("What is on my calendar tomorrow?", "calendar_read", frozenset({"google_calendar"}), False),
    RoutingCase("Find recent PDFs in Drive", "drive_read", frozenset({"google_drive"}), False),
    RoutingCase("Show email, calendar, and Drive updates", "multi_service_read", frozenset({"gmail", "google_calendar", "google_drive"}), False),
    RoutingCase("Prepare me for my next meeting", "workspace_contextual_read", frozenset({"gmail", "google_calendar", "google_drive", "workspace"}), False),
    RoutingCase("Find research material related to Project Alpha", "workspace_contextual_read", frozenset({"workspace"}), False),
    RoutingCase("Find the document", "drive_read", frozenset({"google_drive"}), False),
    RoutingCase("Send John the file", "ambiguous", frozenset({"gmail", "google_drive"}), True),
    RoutingCase("Schedule a meeting tomorrow at 10 AM", "calendar_write", frozenset({"google_calendar"}), True),
    RoutingCase("Delete my meeting with Alex", "calendar_write", frozenset({"google_calendar"}), True),
)

RETRIEVAL_CANDIDATES = [
    {"id": "relevant-mail", "service": "gmail", "title": "Project Alpha research update", "snippet": "experiment results and next steps", "relevant": True},
    {"id": "relevant-drive", "service": "google_drive", "title": "Project Alpha research notes", "snippet": "design and experiment findings", "relevant": True},
    {"id": "weak-one", "service": "gmail", "title": "Weekly digest", "snippet": "general company announcements", "relevant": False},
    {"id": "weak-two", "service": "google_drive", "title": "Resume", "snippet": "software engineering experience", "relevant": False},
    {"id": "weak-three", "service": "gmail", "title": "Course reminder", "snippet": "assignment deadline", "relevant": False},
]


def _precision_at_five(items: list[dict[str, object]]) -> float:
    return sum(bool(item.get("relevant")) for item in items[:5]) / 5


def _intent_family(intent: Intent, query: str) -> str:
    """Map the existing contract to the benchmark's bounded family taxonomy."""
    services = set(intent.required_services)
    lowered = query.casefold()
    is_write = any(
        word in lowered
        for word in ("send ", "delete ", "schedule ", "create ", "move ", "share ")
    )
    if intent.requires_clarification and not services:
        return "ambiguous"
    if is_write:
        if Service.GOOGLE_CALENDAR in services:
            return "calendar_write"
        if Service.GMAIL in services:
            return "gmail_write"
        if Service.GOOGLE_DRIVE in services:
            return "drive_write"
        return "ambiguous"
    if Service.WORKSPACE in services:
        return "workspace_contextual_read"
    native_services = services & {
        Service.GMAIL,
        Service.GOOGLE_CALENDAR,
        Service.GOOGLE_DRIVE,
    }
    if len(native_services) > 1:
        return "multi_service_read"
    if Service.GMAIL in native_services:
        return "gmail_read"
    if Service.GOOGLE_CALENDAR in native_services:
        return "calendar_read"
    if Service.GOOGLE_DRIVE in native_services:
        return "drive_read"
    return "ambiguous"


async def run() -> None:
    settings = get_settings()
    if not settings.groq_api_key:
        print("Laya benchmark not run: GROQ_API_KEY is not configured.")
        return
    laya = build_laya_provider(settings)
    if laya is None:
        print("Laya benchmark not run: Laya is disabled or unavailable.")
        return

    groq = IntentClassifier(GroqProvider(settings))
    results: dict[str, object] = {}
    for mode in ("groq", "hybrid"):
        engine = HybridDecisionEngine(
            groq,
            laya,
            mode=mode,
            minimum_confidence=settings.laya_routing_min_confidence,
        )
        exact = service_tp = service_fp = service_fn = clarification = family = 0
        fallbacks = errors = 0
        latencies: list[float] = []
        for case in ROUTING_CASES:
            started = perf_counter()
            try:
                outcome = await engine.classify(
                    case.query, [], datetime.now(timezone.utc), settings.default_user_timezone
                )
            except Exception:
                errors += 1
                continue
            latencies.append((perf_counter() - started) * 1000)
            actual = {service.value for service in outcome.intent.required_services}
            exact += actual == set(case.services)
            service_tp += len(actual & case.services)
            service_fp += len(actual - case.services)
            service_fn += len(case.services - actual)
            clarification += outcome.intent.requires_clarification == case.clarify
            actual_family = (
                outcome.metadata.intent_family
                if not outcome.metadata.fallback_used
                else _intent_family(outcome.intent, case.query)
            ) or _intent_family(outcome.intent, case.query)
            family += actual_family == case.family
            fallbacks += outcome.metadata.fallback_used
        results[mode] = {
            "intent_family_accuracy": family / len(ROUTING_CASES),
            "service_exact_match": exact / len(ROUTING_CASES),
            "service_precision": service_tp / max(1, service_tp + service_fp),
            "service_recall": service_tp / max(1, service_tp + service_fn),
            "clarification_accuracy": clarification / len(ROUTING_CASES),
            "mean_latency_ms": sum(latencies) / max(1, len(latencies)),
            "fallback_rate": fallbacks / len(ROUTING_CASES),
            "api_error_rate": errors / len(ROUTING_CASES),
        }

    reranker = LayaWorkspaceReranker(
        laya,
        candidate_cap=settings.laya_rerank_candidates,
        relevance_threshold=settings.laya_relevance_threshold,
    )
    rerank_started = perf_counter()
    reranked = await reranker.rerank(
        "Project Alpha research results", RETRIEVAL_CANDIDATES, 5
    )
    results["retrieval"] = {
        "precision_at_5_before": _precision_at_five(RETRIEVAL_CANDIDATES),
        "precision_at_5_after": _precision_at_five(reranked.results),
        "reranking_latency_ms": (perf_counter() - rerank_started) * 1000,
        "fallback_used": reranked.fallback_used,
        "provider_input_tokens": reranked.input_tokens,
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
