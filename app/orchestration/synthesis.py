from typing import Any

from app.llm.prompts import SYNTHESIS_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.schemas.contracts import StepResult


class ResponseSynthesizer:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def synthesize(self, query: str, results: list[StepResult]) -> str:
        output = await self._provider.generate_json(
            SYNTHESIS_SYSTEM_PROMPT,
            {
                "query": query,
                "execution_results": [result.model_dump(mode="json") for result in results],
            },
        )
        response = output.get("response")
        if not isinstance(response, str) or not response.strip():
            raise LLMProviderError("Response synthesizer returned invalid output")
        return response.strip()
