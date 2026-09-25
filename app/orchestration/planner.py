from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.llm.prompts import PLANNER_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.orchestration.registry import AgentRegistry
from app.schemas.contracts import (
    ExecutionPlan,
    ExecutionStep,
    Intent,
    Service,
    StructuredData,
)


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
        reference_time: datetime | None = None,
        _repair_attempt: bool = False,
    ) -> ExecutionPlan:
        if reference_time is None:
            reference_time = datetime.now(timezone.utc)
        elif reference_time.tzinfo is None or reference_time.utcoffset() is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        result = await self._provider.generate_json(
            PLANNER_SYSTEM_PROMPT
            if not _repair_attempt
            else (
                f"{PLANNER_SYSTEM_PROMPT}\n\n"
                "The previous response did not satisfy the ExecutionPlan schema or "
                "operation catalog. Return only a corrected JSON plan using declared "
                "services, operations, argument names, and valid dependencies."
            ),
            {
                "query": query,
                "intent": intent.model_dump(mode="json"),
                "operation_catalog": self._registry.prompt_catalog(),
                "user_timezone": timezone_name,
                "reference_time": reference_time.astimezone(
                    ZoneInfo(timezone_name)
                ).isoformat(),
                "default_meeting_duration_minutes": default_meeting_duration_minutes,
                "planning_rules": [
                    "Use only argument names declared by the selected operation specification.",
                    "For calendar search date ranges use time_min and time_max.",
                    "For Gmail search date ranges use date_from and date_to.",
                    "For Drive search date ranges use modified_after and modified_before.",
                    "Use workspace.workspace_search for semantic or cross-service contextual discovery.",
                    "Use native Google operations for exact IDs, fresh authoritative reads, and writes.",
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
                reference_time=reference_time,
            )
            self._registry.validate_plan(plan)
        except (ValidationError, ValueError) as exc:
            if not _repair_attempt:
                return await self.create_plan(
                    query,
                    intent,
                    timezone_name=timezone_name,
                    default_meeting_duration_minutes=default_meeting_duration_minutes,
                    reference_time=reference_time,
                    _repair_attempt=True,
                )
            raise LLMProviderError("Planner returned an invalid execution plan") from exc
        return plan


def _apply_intent_constraints(
    plan: ExecutionPlan,
    intent: Intent,
    query: str = "",
    timezone_name: str = "UTC",
    default_meeting_duration_minutes: int = 30,
    reference_time: datetime | None = None,
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
                    reference_time=reference_time,
                )
            }
        )
        for step in plan.steps
    ]
    steps = _route_contextual_retrieval(steps, query)
    return plan.model_copy(update={"steps": steps})


def _canonical_arguments(
    service: Service,
    operation: str,
    arguments: StructuredData,
    intent: Intent,
    query: str = "",
    timezone_name: str = "UTC",
    default_meeting_duration_minutes: int = 30,
    reference_time: datetime | None = None,
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
    if service == Service.WORKSPACE and operation == "workspace_search":
        canonical.setdefault("query", query)
        if "services" not in canonical:
            requested_services = [
                requested.value
                for requested in intent.required_services
                if requested != Service.WORKSPACE
            ]
            if requested_services:
                canonical["services"] = requested_services

    if service == Service.GOOGLE_CALENDAR and operation == "search_events":
        if _requests_singular_upcoming_event(query, intent):
            now = reference_time or datetime.now(timezone.utc)
            if now.tzinfo is None or now.utcoffset() is None:
                now = now.replace(tzinfo=timezone.utc)
            local_now = now.astimezone(ZoneInfo(timezone_name))
            canonical["time_min"] = local_now.isoformat()
            canonical["max_results"] = 1

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
        if "time_min" in canonical:
            canonical["time_min"] = max(
                (canonical["time_min"], start),
                key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
            )
        else:
            canonical["time_min"] = start
        canonical["time_max"] = end
    elif service == Service.GMAIL and operation == "search_emails":
        canonical["date_from"] = start.split("T", 1)[0]
        canonical["date_to"] = end.split("T", 1)[0]
    elif service == Service.GOOGLE_DRIVE and operation == "search_files":
        canonical["modified_after"] = start
        canonical["modified_before"] = end
    elif service == Service.WORKSPACE and operation == "workspace_search":
        canonical["date_from"] = start
        canonical["date_to"] = end
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


def _requests_singular_upcoming_event(query: str, intent: Intent) -> bool:
    selector = intent.extracted_entities.get("event_selector")
    if isinstance(selector, str) and selector.lower() in {"next", "upcoming"}:
        return True
    return bool(
        re.search(
            r"\b(?:next|upcoming)\b[^\n,.!?]{0,160}"
            r"\b(?:meeting|event|interview|appointment)\b",
            query,
            flags=re.IGNORECASE,
        )
    )


def _route_contextual_retrieval(
    steps: list[ExecutionStep],
    query: str,
) -> list[ExecutionStep]:
    """Route dependent semantic context lookups through the indexed workspace."""
    if not _requests_contextual_retrieval(query):
        return steps
    calendar_step_ids = [
        step.step_id
        for step in steps
        if step.service == Service.GOOGLE_CALENDAR
        and step.operation == "search_events"
    ]
    if not calendar_step_ids:
        return steps
    calendar_steps = set(calendar_step_ids)

    routed: list[ExecutionStep] = []
    for step in steps:
        target_service: Service | None = None
        if step.service == Service.GMAIL and step.operation == "search_emails":
            target_service = Service.GMAIL
        elif step.service == Service.GOOGLE_DRIVE and step.operation == "search_files":
            target_service = Service.GOOGLE_DRIVE
        calendar_dependency = next(
            (dependency for dependency in step.depends_on if dependency in calendar_steps),
            None,
        )
        if target_service is None or calendar_dependency is None:
            routed.append(step)
            continue
        routed.append(
            step.model_copy(
                update={
                    "service": Service.WORKSPACE,
                    "operation": "workspace_search",
                    "arguments": {
                        "query": {
                            "$step": calendar_dependency,
                            "path": ["events", 0],
                        },
                        "services": [target_service.value],
                        "top_k": 5,
                    },
                }
            )
        )
    desired_services = _contextual_services(query)
    present_services = {
        service
        for step in routed
        if step.service == Service.WORKSPACE
        and step.operation == "workspace_search"
        for service in step.arguments.get("services", [])
        if isinstance(service, str)
    }
    used_ids = {step.step_id for step in routed}
    calendar_dependency = calendar_step_ids[0]
    for service in sorted(desired_services - present_services):
        base_id = f"workspace_{service}"
        step_id = base_id
        suffix = 2
        while step_id in used_ids:
            step_id = f"{base_id}_{suffix}"
            suffix += 1
        used_ids.add(step_id)
        routed.append(
            ExecutionStep(
                step_id=step_id,
                service=Service.WORKSPACE,
                operation="workspace_search",
                arguments={
                    "query": {
                        "$step": calendar_dependency,
                        "path": ["events", 0],
                    },
                    "services": [service],
                    "top_k": 5,
                },
                depends_on=[calendar_dependency],
            )
        )
    return routed


def _requests_contextual_retrieval(query: str) -> bool:
    semantic_context = re.search(
        r"\b(?:related|relevant|context|contextual|prepare|brief|material)\b",
        query,
        flags=re.IGNORECASE,
    )
    event_context = re.search(
        r"\b(?:meeting|event|interview|appointment)\b",
        query,
        flags=re.IGNORECASE,
    )
    return bool(semantic_context and event_context)


def _contextual_services(query: str) -> set[str]:
    services: set[str] = set()
    if re.search(r"\b(?:emails?|messages?|gmail|inbox)\b", query, re.IGNORECASE):
        services.add(Service.GMAIL.value)
    if re.search(r"\b(?:files?|documents?|docs?|drive)\b", query, re.IGNORECASE):
        services.add(Service.GOOGLE_DRIVE.value)
    if not services and re.search(
        r"\b(?:prepare|brief|context|material)\b", query, re.IGNORECASE
    ):
        services.update({Service.GMAIL.value, Service.GOOGLE_DRIVE.value})
    return services
