from datetime import datetime, timedelta
import re

from pydantic import ValidationError

from app.llm.prompts import PLANNER_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.orchestration.registry import AgentRegistry
from app.schemas.contracts import ExecutionPlan, Intent, Service, StructuredData


class QueryPlanner:
    def __init__(self, provider: LLMProvider, registry: AgentRegistry) -> None:
        self._provider = provider
        self._registry = registry

    async def create_plan(
        self,
        query: str,
        intent: Intent,
        timezone_name: str = "UTC",
        default_meeting_duration_minutes: int = 30,
    ) -> ExecutionPlan:
        result = await self._provider.generate_json(
            PLANNER_SYSTEM_PROMPT,
            {
                "query": query,
                "intent": intent.model_dump(mode="json"),
                "operation_catalog": self._registry.prompt_catalog(),
                "user_timezone": timezone_name,
                "default_meeting_duration_minutes": default_meeting_duration_minutes,
                "planning_rules": [
                    "Use only argument names declared by the selected operation specification.",
                    "For calendar search date ranges use time_min and time_max.",
                    "For Gmail search date ranges use date_from and date_to.",
                    "For Drive search date ranges use modified_after and modified_before.",
                ],
            },
        )
        try:
            plan = ExecutionPlan.model_validate(result)
            plan = _apply_intent_constraints(
                plan,
                intent,
                query=query,
                timezone_name=timezone_name,
                default_meeting_duration_minutes=default_meeting_duration_minutes,
            )
            self._registry.validate_plan(plan)
        except (ValidationError, ValueError) as exc:
            raise LLMProviderError("Planner returned an invalid execution plan") from exc
        return plan


def _apply_intent_constraints(
    plan: ExecutionPlan,
    intent: Intent,
    query: str = "",
    timezone_name: str = "UTC",
    default_meeting_duration_minutes: int = 30,
) -> ExecutionPlan:
    steps = [
        step.model_copy(
            update={
                "arguments": _canonical_arguments(
                    step.service,
                    step.operation,
                    step.arguments,
                    intent,
                    query=query,
                    timezone_name=timezone_name,
                    default_meeting_duration_minutes=default_meeting_duration_minutes,
                )
            }
        )
        for step in plan.steps
    ]
    return plan.model_copy(update={"steps": steps})


def _canonical_arguments(
    service: Service,
    operation: str,
    arguments: StructuredData,
    intent: Intent,
    query: str = "",
    timezone_name: str = "UTC",
    default_meeting_duration_minutes: int = 30,
) -> StructuredData:
    canonical = dict(arguments)
    if service == Service.GOOGLE_CALENDAR and operation == "create_event":
        entities = intent.extracted_entities
        entity_start = entities.get("start_time") or entities.get("start")
        entity_end = entities.get("end_time") or entities.get("end")
        if isinstance(entity_start, str):
            canonical["start"] = entity_start
            if isinstance(entity_end, str):
                canonical["end"] = entity_end
            else:
                duration = entities.get("duration_minutes")
                if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
                    duration = default_meeting_duration_minutes
                canonical["end"] = _default_end_time(canonical["start"], duration)
        elif "start" in canonical and "end" not in canonical:
            canonical["end"] = _default_end_time(
                canonical["start"], default_meeting_duration_minutes
            )
        entity_attendees = entities.get("attendees")
        if isinstance(entity_attendees, list) and all(
            isinstance(item, str) and item for item in entity_attendees
        ):
            canonical["attendees"] = entity_attendees
        elif isinstance(entities.get("attendee_email"), str):
            canonical["attendees"] = [entities["attendee_email"]]
        canonical["timezone"] = timezone_name
        canonical["create_google_meet"] = _requests_google_meet(query)

    date_range = intent.extracted_entities.get("date_range")
    if not isinstance(date_range, dict):
        date_range = intent.extracted_entities.get("time_range")
    if not isinstance(date_range, dict):
        return canonical

    start = date_range.get("start")
    end = date_range.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return canonical

    if service == Service.GOOGLE_CALENDAR and operation == "search_events":
        canonical["time_min"] = start
        canonical["time_max"] = end
    elif service == Service.GMAIL and operation == "search_emails":
        canonical["date_from"] = start.split("T", 1)[0]
        canonical["date_to"] = end.split("T", 1)[0]
    elif service == Service.GOOGLE_DRIVE and operation == "search_files":
        canonical["modified_after"] = start
        canonical["modified_before"] = end
    else:
        return canonical

    for alias in ("date_range", "time_range", "start_date", "end_date", "time_minimum", "time_maximum"):
        canonical.pop(alias, None)
    return canonical


def _default_end_time(start: object, duration_minutes: int) -> str:
    if not isinstance(start, str):
        raise ValueError("Calendar event start must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Calendar event start must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Calendar event start must include a timezone")
    return (parsed + timedelta(minutes=duration_minutes)).isoformat()


def _requests_google_meet(query: str) -> bool:
    return bool(re.search(r"\bgoogle\s+meet\b", query, flags=re.IGNORECASE))
