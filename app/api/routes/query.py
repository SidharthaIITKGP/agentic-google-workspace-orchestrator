from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, DatabaseSession
from app.core.config import get_settings
from app.db.models import Conversation, Message
from app.llm.provider import GroqProvider, LLMProviderError
from app.orchestration.classifier import IntentClassifier
from app.orchestration.executor import DAGExecutor
from app.orchestration.planner import QueryPlanner
from app.orchestration.runtime import build_agent_registry
from app.orchestration.synthesis import ResponseSynthesizer
from app.schemas.api import QueryRequest, QueryResponse
from app.schemas.contracts import ExecutionStatus, StepResult

router = APIRouter(prefix="/api/v1", tags=["queries"])


@router.post("/query", response_model=QueryResponse)
async def submit_query(
    request: QueryRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
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
        intent = await classifier.classify(
            query=request.query,
            context=context,
            reference_time=datetime.now(timezone.utc),
            timezone_name="UTC",
        )
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
            )

        registry = build_agent_registry(session, user_id, settings)
        plan = await QueryPlanner(provider, registry).create_plan(request.query, intent)
        outcome = await DAGExecutor(session, registry).execute(
            user_id=user_id,
            conversation_id=conversation.id,
            intent=intent,
            plan=plan,
        )
        try:
            response_text = await ResponseSynthesizer(provider).synthesize(
                request.query, outcome.results
            )
        except LLMProviderError:
            response_text = _grounded_fallback(outcome.results)
    except LLMProviderError as exc:
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
        {"step_id": result.step_id, "approval_id": result.data.get("approval_id")}
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
    completed = sum(result.status == ExecutionStatus.COMPLETED for result in results)
    pending = sum(result.status == ExecutionStatus.AWAITING_APPROVAL for result in results)
    failed = sum(
        result.status in {ExecutionStatus.FAILED, ExecutionStatus.SKIPPED}
        for result in results
    )
    parts = [f"Completed {completed} step(s) using the available service results."]
    if pending:
        parts.append(f"{pending} action(s) are waiting for approval.")
    if failed:
        parts.append(f"{failed} step(s) could not be completed.")
    return " ".join(parts)
