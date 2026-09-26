from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from app.llm.laya import (
    INTENT_FAMILIES,
    SERVICE_QUESTIONS,
    LayaDecisionProviderProtocol,
    LayaRoutingDecision,
)
from app.orchestration.classifier import IntentClassifier
from app.schemas.contracts import Intent, Service


logger = logging.getLogger(__name__)
_WRITE_REQUEST = re.compile(
    r"\b(send|delete|remove|move|reschedule|schedule|create|share|invite|cancel|"
    r"update|edit|rename|reply|forward|upload|modify)\b",
    re.IGNORECASE,
)
_IMPERATIVE_WRITE_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:email|message|mail)\b",
    re.IGNORECASE,
)
_WRITE_INTENT_NAME = re.compile(
    r"(?:^|_)(?:send|delete|remove|move|reschedule|schedule|create|share|invite|"
    r"cancel|update|edit|rename|reply|forward|upload|modify)(?:_|$)",
    re.IGNORECASE,
)
_MAX_CONTEXT_MESSAGES = 3
_MAX_CONTEXT_CHARS = 800


def _minimal_routing_context(
    context: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep routing context useful without forwarding large conversation payloads."""
    return [
        {
            "role": str(message.get("role", ""))[:20],
            "content": str(message.get("content", ""))[:_MAX_CONTEXT_CHARS],
        }
        for message in context[-_MAX_CONTEXT_MESSAGES:]
    ]


def _is_write_request(query: str, intent: Intent) -> bool:
    return bool(
        _WRITE_REQUEST.search(query)
        or _IMPERATIVE_WRITE_REQUEST.search(query)
        or _WRITE_INTENT_NAME.search(intent.intent_name)
    )


def _valid_decision(decision: LayaRoutingDecision) -> bool:
    if decision.intent_family not in INTENT_FAMILIES:
        return False
    if set(decision.service_probabilities) != set(SERVICE_QUESTIONS):
        return False
    values = [
        decision.intent_confidence,
        decision.can_proceed_probability,
        *decision.service_probabilities.values(),
    ]
    return all(isinstance(value, (int, float)) and 0.0 <= value <= 1.0 for value in values)


def _family_matches_services(
    decision: LayaRoutingDecision, minimum_confidence: float
) -> bool:
    selected = {
        service
        for service, probability in decision.service_probabilities.items()
        if probability >= minimum_confidence
    }
    required_by_family = {
        "gmail_read": "gmail",
        "gmail_write": "gmail",
        "calendar_read": "google_calendar",
        "calendar_write": "google_calendar",
        "drive_read": "google_drive",
        "drive_write": "google_drive",
        "workspace_contextual_read": "workspace",
    }
    required = required_by_family.get(decision.intent_family)
    if required is not None:
        return required in selected
    if decision.intent_family == "multi_service_read":
        native = {"gmail", "google_calendar", "google_drive"}
        return len(selected & native) >= 2
    return True


@dataclass(frozen=True)
class DecisionMetadata:
    decision_provider: str
    intent_family: str | None = None
    confidence: float | None = None
    model: str | None = None
    latency_ms: float | None = None
    fallback_used: bool = False
    input_tokens: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class ClassifiedIntent:
    intent: Intent
    metadata: DecisionMetadata


class HybridDecisionEngine:
    """Adds bounded Laya routing while retaining Groq extraction and safety policy."""

    def __init__(
        self,
        groq_classifier: IntentClassifier,
        laya: LayaDecisionProviderProtocol | None,
        *,
        mode: str,
        minimum_confidence: float,
    ) -> None:
        self._groq = groq_classifier
        self._laya = laya
        self._mode = mode
        self._minimum_confidence = minimum_confidence

    async def classify(
        self,
        query: str,
        context: list[dict[str, str]],
        reference_time: datetime,
        timezone_name: str,
    ) -> ClassifiedIntent:
        if self._mode == "groq" or self._laya is None:
            intent = await self._groq.classify(
                query, context, reference_time, timezone_name
            )
            return ClassifiedIntent(
                intent,
                DecisionMetadata(
                    decision_provider="groq_fallback" if self._mode != "groq" else "groq",
                    fallback_used=self._mode != "groq",
                ),
            )

        decision_result, intent_result = await asyncio.gather(
            self._laya.route(
                {
                    "request": query[:4000],
                    "recent_context": _minimal_routing_context(context),
                    "supported_services": [service.value for service in Service],
                    "request_kind": (
                        "write_or_destructive"
                        if _WRITE_REQUEST.search(query)
                        or _IMPERATIVE_WRITE_REQUEST.search(query)
                        else "read_or_unknown"
                    ),
                }
            ),
            self._groq.classify(
                query, context, reference_time, timezone_name
            ),
            return_exceptions=True,
        )
        if isinstance(intent_result, BaseException):
            raise intent_result
        intent = intent_result
        if isinstance(decision_result, BaseException):
            return ClassifiedIntent(
                intent,
                DecisionMetadata(decision_provider="groq_fallback", fallback_used=True),
            )
        decision = decision_result
        if not _valid_decision(decision):
            return ClassifiedIntent(
                intent,
                DecisionMetadata(
                    decision_provider="groq_fallback",
                    model=decision.model,
                    latency_ms=decision.latency_ms,
                    fallback_used=True,
                    input_tokens=decision.input_tokens,
                ),
            )
        probabilities = decision.service_probabilities
        uncertain = (
            decision.intent_confidence < self._minimum_confidence
            or any(
                1.0 - self._minimum_confidence
                < probability
                < self._minimum_confidence
                for probability in probabilities.values()
            )
            or not _family_matches_services(decision, self._minimum_confidence)
        )
        if uncertain:
            return ClassifiedIntent(
                intent,
                DecisionMetadata(
                    decision_provider="groq_fallback",
                    intent_family=decision.intent_family,
                    confidence=decision.intent_confidence,
                    model=decision.model,
                    latency_ms=decision.latency_ms,
                    fallback_used=True,
                    input_tokens=decision.input_tokens,
                ),
            )

        services = [
            Service(service)
            for service, probability in probabilities.items()
            if probability >= self._minimum_confidence
        ]
        if services:
            intent = intent.model_copy(update={"required_services": services})

        # Laya is never allowed to weaken uncertainty around side effects.
        if (
            not _is_write_request(query, intent)
            and decision.can_proceed_probability >= self._minimum_confidence
        ):
            intent = intent.model_copy(
                update={
                    "requires_clarification": False,
                    "clarification_question": None,
                }
            )
        metadata = DecisionMetadata(
            decision_provider="laya",
            intent_family=decision.intent_family,
            confidence=decision.intent_confidence,
            model=decision.model,
            latency_ms=decision.latency_ms,
            fallback_used=False,
            input_tokens=decision.input_tokens,
        )
        logger.info("Laya routing decision", extra=metadata.as_dict())
        return ClassifiedIntent(intent, metadata)
