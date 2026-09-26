from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

import httpx


logger = logging.getLogger(__name__)
_PROVIDERS: dict[tuple[str, str, str, float], "LayaDecisionProvider"] = {}

INTENT_FAMILIES: dict[str, str] = {
    "gmail_read": "Read or search Gmail only",
    "calendar_read": "Read or search Calendar only",
    "drive_read": "Read or search Drive only",
    "workspace_contextual_read": "Semantic retrieval using workspace context",
    "multi_service_read": "Read from two or more Workspace services",
    "gmail_write": "Send or modify Gmail data",
    "calendar_write": "Create, update, move, or delete Calendar data",
    "drive_write": "Create, move, share, or modify Drive data",
    "ambiguous": "Cannot safely determine the intended operation",
    "unsupported": "Outside supported Gmail, Calendar, and Drive operations",
}
SERVICE_QUESTIONS: dict[str, str] = {
    "gmail": "needs_gmail",
    "google_calendar": "needs_calendar",
    "google_drive": "needs_drive",
    "workspace": "needs_workspace_search",
}
_SERVICE_INSTRUCTIONS = {
    "needs_gmail": "Does this request require Gmail data or operations?",
    "needs_calendar": "Does this request require Google Calendar data or operations?",
    "needs_drive": "Does this request require Google Drive data or operations?",
    "needs_workspace_search": "Does this require semantic search over indexed workspace content?",
}
_SERVICE_CRITERIA: dict[str, dict[str, str]] = {
    "needs_gmail": {
        "true": "The request needs email, inbox, message, thread, draft, label, send, or reply data/actions.",
        "false": "The request can be completed without Gmail data or operations.",
    },
    "needs_calendar": {
        "true": "The request needs events, meetings, schedules, availability, or Calendar write operations.",
        "false": "The request can be completed without Google Calendar data or operations.",
    },
    "needs_drive": {
        "true": "The request needs files, folders, documents, PDFs, sharing, moving, or Drive search/actions.",
        "false": "The request can be completed without Google Drive data or operations.",
    },
    "needs_workspace_search": {
        "true": "The request needs semantic or contextual evidence retrieval from indexed workspace content.",
        "false": "The request is exact/native, a write, or otherwise does not need indexed contextual retrieval.",
    },
}


class LayaProviderError(RuntimeError):
    """Safe provider error that never includes request content or credentials."""


@dataclass(frozen=True)
class LayaRoutingDecision:
    intent_family: str
    intent_confidence: float
    service_probabilities: dict[str, float]
    can_proceed_probability: float
    model: str
    latency_ms: float
    input_tokens: int | None = None


@dataclass(frozen=True)
class LayaRelevanceDecision:
    probabilities: list[float]
    model: str
    latency_ms: float
    input_tokens: int | None = None


class LayaDecisionProviderProtocol(Protocol):
    async def route(self, state: dict[str, Any]) -> LayaRoutingDecision: ...

    async def relevance(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> LayaRelevanceDecision: ...


class LayaDecisionProvider:
    """Async adapter for Laya's System One HTTP endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "typed-decisions",
        api_key: str = "",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise LayaProviderError("LAYA_BASE_URL must be an HTTP(S) URL")
        self._model = model
        self._timeout_seconds = timeout_seconds
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def model(self) -> str:
        return self._model

    async def close(self) -> None:
        await self._client.aclose()

    async def route(self, state: dict[str, Any]) -> LayaRoutingDecision:
        questions: dict[str, dict[str, Any]] = {
            "intent_family": {
                "type": "choice",
                "instructions": "Choose the single best bounded intent family.",
                "criteria": INTENT_FAMILIES,
            },
            **{
                question: {
                    "type": "noul",
                    "instructions": _SERVICE_INSTRUCTIONS[question],
                    "criteria": _SERVICE_CRITERIA[question],
                }
                for question in SERVICE_QUESTIONS.values()
            },
            "can_proceed": {
                "type": "noul",
                "instructions": "Can this safely proceed without clarification?",
                "criteria": {
                    "true": "Required read criteria are inferable, or a requested write has a safe, unambiguous target and required details.",
                    "false": "A write target or required write detail is ambiguous, or proceeding could cause an unintended side effect.",
                },
            },
        }
        started = perf_counter()
        response = await self._call(state, questions)
        try:
            answers = response["answers"]
            family_answer = answers["intent_family"]
            family = str(family_answer["choice"])
            if family not in INTENT_FAMILIES:
                raise ValueError("unknown intent family")
            decision = LayaRoutingDecision(
                intent_family=family,
                intent_confidence=_choice_confidence(family_answer, family),
                service_probabilities={
                    service: _probability(answers[question]["noul"])
                    for service, question in SERVICE_QUESTIONS.items()
                },
                can_proceed_probability=_probability(answers["can_proceed"]["noul"]),
                model=str(response.get("model", self._model)),
                latency_ms=(perf_counter() - started) * 1000,
                input_tokens=_input_tokens(response),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LayaProviderError("Laya returned an unexpected routing response") from exc
        _log_decision("routing", decision.model, decision.latency_ms, decision.input_tokens)
        return decision

    async def relevance(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> LayaRelevanceDecision:
        questions = {
            f"candidate_{index}": {
                "type": "noul",
                "instructions": "Is this meaningfully relevant evidence for the request?",
                "criteria": {
                    "true": "The candidate contains specific evidence that directly supports or answers the request.",
                    "false": "The candidate is unrelated, merely shares generic words, or provides no useful evidence.",
                },
            }
            for index in range(len(candidates))
        }
        started = perf_counter()
        response = await self._call(
            {"request": query[:1000], "candidates": candidates}, questions
        )
        try:
            answers = response["answers"]
            decision = LayaRelevanceDecision(
                probabilities=[
                    _probability(answers[f"candidate_{index}"]["noul"])
                    for index in range(len(candidates))
                ],
                model=str(response.get("model", self._model)),
                latency_ms=(perf_counter() - started) * 1000,
                input_tokens=_input_tokens(response),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LayaProviderError("Laya returned an unexpected relevance response") from exc
        _log_decision(
            "retrieval_relevance", decision.model, decision.latency_ms,
            decision.input_tokens, candidate_count=len(candidates)
        )
        return decision

    async def _call(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        payload = {"model": self._model, "state": state, "questions": questions}
        try:
            async with asyncio.timeout(self._timeout_seconds):
                response = await self._client.post("/v1/systemone", json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("response must be an object")
            return data
        except Exception as exc:
            logger.warning(
                "Laya decision failed",
                extra={
                    "decision_provider": "laya",
                    "model": self._model,
                    "error_type": type(exc).__name__,
                    "fallback_used": True,
                },
            )
            raise LayaProviderError("Laya decision request failed") from exc


def build_laya_provider(settings: Any) -> LayaDecisionProviderProtocol | None:
    if not settings.laya_enabled:
        return None
    try:
        key = (
            settings.laya_base_url,
            settings.laya_api_key,
            settings.laya_model,
            settings.laya_timeout_seconds,
        )
        provider = _PROVIDERS.get(key)
        if provider is None:
            provider = LayaDecisionProvider(
                base_url=settings.laya_base_url,
                api_key=settings.laya_api_key,
                model=settings.laya_model,
                timeout_seconds=settings.laya_timeout_seconds,
            )
            _PROVIDERS[key] = provider
        return provider
    except LayaProviderError:
        logger.warning("Laya is unavailable; Groq fallback will be used")
        return None


async def close_laya_providers() -> None:
    providers = list(_PROVIDERS.values())
    _PROVIDERS.clear()
    for provider in providers:
        await provider.close()


def _probability(value: Any) -> float:
    probability = float(value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be finite and between zero and one")
    return probability


def _choice_confidence(answer: dict[str, Any], choice: str) -> float:
    """Return confidence in the selected answer, not distribution entropy."""
    if "answer_confidence" in answer:
        return _probability(answer["answer_confidence"])
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, dict) and choice in probabilities:
        return _probability(probabilities[choice])
    return _probability(answer["confidence"])


def _input_tokens(response: dict[str, Any]) -> int | None:
    usage = response.get("usage")
    value = usage.get("input_tokens") if isinstance(usage, dict) else None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _log_decision(
    decision_type: str, model: str, latency_ms: float,
    input_tokens: int | None, **extra: object
) -> None:
    logger.info(
        "Laya decision completed",
        extra={
            "decision_type": decision_type,
            "decision_provider": "laya",
            "model": model,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "fallback_used": False,
            **extra,
        },
    )
