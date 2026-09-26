import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, DatabaseSession, RedisCacheDependency
from app.core.config import get_settings
from app.db.models import Conversation, Message
from app.llm.provider import GroqProvider, LLMProviderError
from app.llm.laya import build_laya_provider
from app.orchestration.classifier import IntentClassifier
from app.orchestration.decisions import HybridDecisionEngine
from app.orchestration.compaction import compact_results_for_synthesis
from app.orchestration.executor import DAGExecutor
from app.orchestration.planner import QueryPlanner
from app.orchestration.runtime import build_agent_registry
from app.orchestration.synthesis import ResponseSynthesizer, grounded_response
from app.schemas.api import QueryRequest, QueryResponse
from app.schemas.contracts import ExecutionStatus, StepResult, StructuredData

router = APIRouter(prefix="/api/v1", tags=["queries"])
logger = logging.getLogger(__name__)


@router.post("/query", response_model=QueryResponse)
async def submit_query(
    request: QueryRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
    cache: RedisCacheDependency,
) -> QueryResponse:
    conversation = await _load_or_create_conversation(
        session, user_id, request.conversation_id
    )
    context = await _recent_context(session, conversation.id)
    session.add(Message(conversation_id=conversation.id, role="user", content=request.query))
    await session.flush()

    settings = get_settings()
    try:
        provider = GroqProvider(settings)
        classifier = IntentClassifier(provider)
        decision_engine = HybridDecisionEngine(
            classifier,
            build_laya_provider(settings),
            mode=settings.decision_engine,
            minimum_confidence=settings.laya_routing_min_confidence,
        )
        reference_time = datetime.now(timezone.utc)
        classified = await decision_engine.classify(
            query=request.query,
            context=context,
            reference_time=reference_time,
            timezone_name=settings.default_user_timezone,
        )
        intent = classified.intent
        decision_metadata = classified.metadata.as_dict()
        if intent.requires_clarification:
            clarification = intent.clarification_question or "Could you clarify your request?"
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=clarification,
                )
            )
            await session.commit()
            return QueryResponse(
                response=clarification,
                conversation_id=conversation.id,
                intent=intent,
                decision_metadata=decision_metadata,
            )

        registry = build_agent_registry(session, user_id, settings, cache)
        plan = await QueryPlanner(provider, registry).create_plan(
            request.query,
            intent,
            timezone_name=settings.default_user_timezone,
            default_meeting_duration_minutes=settings.default_meeting_duration_minutes,
            reference_time=reference_time,
        )
        outcome = await DAGExecutor(session, registry).execute(
            user_id=user_id,
            conversation_id=conversation.id,
            intent=intent,
            plan=plan,
        )
        try:
            response_text = await ResponseSynthesizer(provider).synthesize(
                request.query, compact_results_for_synthesis(outcome.results)
            )
        except LLMProviderError:
            response_text = _grounded_fallback(outcome.results)
    except LLMProviderError as exc:
        logger.warning("Query interpretation failed: %s", str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The request could not be interpreted safely",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="The generated request was invalid") from exc

    actions_taken = [
        {"step_id": result.step_id, "data": result.data}
        for result in outcome.results
        if result.status == ExecutionStatus.COMPLETED
    ]
    pending_approvals = [
        {
            "step_id": result.step_id,
            "approval_id": result.data.get("approval_id"),
            **(
                {"proposed_action": preview}
                if (preview := _sanitized_approval_preview(
                    result.data.get("proposed_action")
                ))
                else {}
            ),
        }
        for result in outcome.results
        if result.status == ExecutionStatus.AWAITING_APPROVAL
    ]
    errors = [
        {
            "step_id": result.step_id,
            "status": result.status.value,
            "error": result.error.model_dump(mode="json") if result.error else None,
        }
        for result in outcome.results
        if result.status in {ExecutionStatus.FAILED, ExecutionStatus.SKIPPED}
    ]
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=response_text,
        )
    )
    await session.commit()
    return QueryResponse(
        response=response_text,
        conversation_id=conversation.id,
        execution_id=outcome.execution_id,
        intent=intent,
        actions_taken=actions_taken,
        pending_approvals=pending_approvals,
        errors=errors,
        decision_metadata=decision_metadata,
    )


async def _load_or_create_conversation(
    session: DatabaseSession,
    user_id: UUID,
    conversation_id: UUID | None,
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation
    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()
    return conversation


async def _recent_context(
    session: DatabaseSession,
    conversation_id: UUID,
) -> list[dict[str, str]]:
    messages = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(5)
            )
        ).all()
    )
    messages.reverse()
    return [{"role": message.role, "content": message.content} for message in messages]


def _grounded_fallback(results: list[StepResult]) -> str:
    return grounded_response(compact_results_for_synthesis(results))


def _sanitized_approval_preview(value: object) -> StructuredData | None:
    if not isinstance(value, dict):
        return None
    preview: StructuredData = {}
    for key in ("service", "operation"):
        item = value.get(key)
        if isinstance(item, str):
            preview[key] = item
    arguments = value.get("arguments")
    source = arguments if isinstance(arguments, dict) else value
    safe_arguments: StructuredData = {}
    for key in (
        "title",
        "start",
        "end",
        "attendees",
        "create_google_meet",
        "event_id",
        "message_id",
        "file_id",
        "to",
        "subject",
    ):
        item = source.get(key)
        if isinstance(item, (str, bool)):
            safe_arguments[key] = item
        elif key == "attendees" and isinstance(item, list):
            safe_arguments[key] = [
                attendee for attendee in item[:10] if isinstance(attendee, str)
            ]
    if safe_arguments:
        preview["arguments"] = safe_arguments
    return preview or None


def _compact_results_for_synthesis(results: list[StepResult]) -> list[StepResult]:
    return [
        result.model_copy(update={"data": _compact_result_data(result.data)})
        for result in results
    ]


def _compact_result_data(data: StructuredData) -> StructuredData:
    events = data.get("events")
    if not isinstance(events, list):
        return data

    compact_events = []
    for event in events[:20]:
        if not isinstance(event, dict):
            continue
        compact = {
            key: event[key]
            for key in ("title", "start", "end", "attendees", "status")
            if key in event
        }
        description = event.get("description")
        if isinstance(description, str) and description:
            compact["description"] = description[:500]
        compact_events.append(compact)
    return {
        "events": compact_events,
        "next_page_token": data.get("next_page_token"),
    }
