import json
import logging
from typing import Any, Protocol

from openai import AsyncOpenAI

from app.core.config import Settings


logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    pass


GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"


class LLMProvider(Protocol):
    async def generate_json(
        self,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class GroqProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.groq_api_key:
            raise LLMProviderError("GROQ_API_KEY is not configured")
        self._model = settings.groq_model
        self._client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url=GROQ_OPENAI_BASE_URL,
            timeout=settings.llm_timeout_seconds,
            max_retries=2,
        )

    async def generate_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": f"{system_prompt}\n\nReturn a valid JSON object.",
                    },
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
            )
            content = completion.choices[0].message.content
            parsed = json.loads(content or "")
        except Exception as exc:
            logger.warning(
                "LLM request failed (%s, status=%s)",
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise LLMProviderError("The language model request failed") from exc
        if not isinstance(parsed, dict):
            raise LLMProviderError("The language model returned invalid structured output")
        return parsed
