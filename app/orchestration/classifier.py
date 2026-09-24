from datetime import datetime
from pydantic import ValidationError

from app.llm.prompts import INTENT_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.orchestration.temporal import normalize_temporal_expressions
from app.schemas.contracts import Intent


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
        result = await self._provider.generate_json(
            INTENT_SYSTEM_PROMPT,
            {
                "query": query,
                "recent_context": context,
                "reference_time": reference_time.isoformat(),
                "timezone": timezone_name,
                "temporal_hints": temporal_hints,
            },
        )
        try:
            return Intent.model_validate(result)
        except ValidationError as exc:
            raise LLMProviderError("Intent classifier returned invalid output") from exc
