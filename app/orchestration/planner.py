from pydantic import ValidationError

from app.llm.prompts import PLANNER_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.orchestration.registry import AgentRegistry
from app.schemas.contracts import ExecutionPlan, Intent


class QueryPlanner:
    def __init__(self, provider: LLMProvider, registry: AgentRegistry) -> None:
        self._provider = provider
        self._registry = registry

    async def create_plan(self, query: str, intent: Intent) -> ExecutionPlan:
        result = await self._provider.generate_json(
            PLANNER_SYSTEM_PROMPT,
            {
                "query": query,
                "intent": intent.model_dump(mode="json"),
                "operation_catalog": self._registry.prompt_catalog(),
            },
        )
        try:
            plan = ExecutionPlan.model_validate(result)
            self._registry.validate_plan(plan)
        except (ValidationError, ValueError) as exc:
            raise LLMProviderError("Planner returned an invalid execution plan") from exc
        return plan
