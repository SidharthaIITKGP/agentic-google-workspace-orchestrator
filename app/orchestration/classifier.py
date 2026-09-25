from datetime import datetime
import re

from pydantic import ValidationError

from app.llm.prompts import INTENT_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.orchestration.temporal import normalize_temporal_expressions
from app.schemas.contracts import Intent, Service


_MAX_STRUCTURED_OUTPUT_ATTEMPTS = 2
_REPAIR_INSTRUCTION = (
    "The previous response did not satisfy the required Intent schema. "
    "Return only one JSON object with valid field names, service enum values, "
    "and JSON-compatible entity values."
)

_READ_ONLY_REQUEST = re.compile(
    r"\b(find|search|show|list|locate|retrieve|prepare|brief|summarize|summarise|"
    r"review|identify|what(?:'s|\s+is)|who|when|where)\b",
    flags=re.IGNORECASE,
)
_SIDE_EFFECTING_REQUEST = re.compile(
    r"\b(send|delete|remove|move|reschedule|schedule|create|share|invite|cancel|"
    r"update|edit|rename|draft|reply|forward|upload|modify)\b",
    flags=re.IGNORECASE,
)


class IntentClassifier:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def classify(
        self,
        query: str,
        context: list[dict[str, str]],
        reference_time: datetime,
        timezone_name: str,
    ) -> Intent:
        temporal_hints = normalize_temporal_expressions(
            query, reference_time, timezone_name
        )
        payload = {
            "query": query,
            "recent_context": context,
            "reference_time": reference_time.isoformat(),
            "timezone": timezone_name,
            "temporal_hints": temporal_hints,
        }
        last_validation_error: ValidationError | ValueError | None = None

        for attempt in range(_MAX_STRUCTURED_OUTPUT_ATTEMPTS):
            prompt = INTENT_SYSTEM_PROMPT
            if attempt:
                prompt = f"{prompt}\n\n{_REPAIR_INSTRUCTION}"
            result = await self._provider.generate_json(prompt, payload)
            try:
                intent = Intent.model_validate(result)
                intent = _apply_clarification_policy(query, intent)
                if not intent.requires_clarification and not intent.required_services:
                    raise ValueError(
                        "A resolved intent must select at least one service"
                    )
                return intent
            except (ValidationError, ValueError) as exc:
                last_validation_error = exc

        raise LLMProviderError(
            "Intent classifier returned invalid output after a repair attempt"
        ) from last_validation_error


def _apply_clarification_policy(query: str, intent: Intent) -> Intent:
    """Permit semantic inference for reads without relaxing write safety."""
    if not intent.requires_clarification:
        return intent
    if _SIDE_EFFECTING_REQUEST.search(query):
        return intent
    if not _READ_ONLY_REQUEST.search(query):
        return intent
    services = list(intent.required_services)
    service_hints = (
        (Service.GMAIL, r"\b(gmail|e-?mails?|messages?|inboxes?)\b"),
        (
            Service.GOOGLE_CALENDAR,
            r"\b(calendars?|meetings?|events?|interviews?|appointments?)\b",
        ),
        (Service.GOOGLE_DRIVE, r"\b(drive|files?|documents?|docs?|folders?)\b"),
    )
    for service, pattern in service_hints:
        if service not in services and re.search(pattern, query, flags=re.IGNORECASE):
            services.append(service)
    if not services:
        return intent
    return intent.model_copy(
        update={
            "required_services": services,
            "requires_clarification": False,
            "clarification_question": None,
        }
    )
