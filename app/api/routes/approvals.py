from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, DatabaseSession
from app.core.config import get_settings
from app.db.models import ActionApproval, AuditLog, Execution, ExecutionStep
from app.orchestration.runtime import build_agent_registry
from app.schemas.api import ApprovalResponse
from app.schemas.contracts import ExecutionStatus, Service

router = APIRouter(prefix="/api/v1/actions", tags=["approvals"])


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_action(
    approval_id: UUID,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApprovalResponse:
    approval = await _pending_approval(session, approval_id, user_id)
    action = approval.proposed_action
    try:
        service = Service(action["service"])
        operation = action["operation"]
        arguments = action["arguments"]
        if not isinstance(operation, str) or not isinstance(arguments, dict):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="Stored action is invalid") from exc

    registry = build_agent_registry(session, user_id, get_settings())
    registry.validate_operation(service, operation)
    try:
        result = await registry.execute(service, operation, arguments)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The approved action could not be executed",
        ) from exc
    step = await _execution_step(session, approval)
    step.status = result.status.value
    step.result = result.data
    step.error_details = result.error.model_dump(mode="json") if result.error else None
    approval.status = "approved" if result.status == ExecutionStatus.COMPLETED else "failed"
    session.add(
        AuditLog(
            user_id=user_id,
            execution_id=approval.execution_id,
            action="action_approval_executed",
            details={
                "approval_id": str(approval.id),
                "step_id": approval.step_id,
                "status": approval.status,
            },
        )
    )
    await _refresh_execution_status(session, approval.execution_id)
    await session.commit()
    return ApprovalResponse(
        approval_id=approval.id,
        status=approval.status,
        result=result.data,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_action(
    approval_id: UUID,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApprovalResponse:
    approval = await _pending_approval(session, approval_id, user_id)
    approval.status = "rejected"
    step = await _execution_step(session, approval)
    step.status = ExecutionStatus.SKIPPED.value
    step.error_details = {
        "code": "approval_rejected",
        "message": "The user rejected this action",
    }
    execution = await session.get(Execution, approval.execution_id)
    if execution is not None:
        execution.status = ExecutionStatus.FAILED.value
    session.add(
        AuditLog(
            user_id=user_id,
            execution_id=approval.execution_id,
            action="action_approval_rejected",
            details={"approval_id": str(approval.id), "step_id": approval.step_id},
        )
    )
    await session.commit()
    return ApprovalResponse(approval_id=approval.id, status="rejected")


async def _pending_approval(
    session: DatabaseSession,
    approval_id: UUID,
    user_id: CurrentUserId,
) -> ActionApproval:
    approval = await session.scalar(
        select(ActionApproval).where(
            ActionApproval.id == approval_id,
            ActionApproval.user_id == user_id,
        ).with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != ExecutionStatus.AWAITING_APPROVAL.value:
        raise HTTPException(status_code=409, detail="Approval is no longer pending")
    return approval


async def _execution_step(
    session: DatabaseSession,
    approval: ActionApproval,
) -> ExecutionStep:
    step = await session.scalar(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == approval.execution_id,
            ExecutionStep.step_id == approval.step_id,
        )
    )
    if step is None:
        raise HTTPException(status_code=409, detail="Approval step not found")
    return step


async def _refresh_execution_status(session: DatabaseSession, execution_id: UUID) -> None:
    execution = await session.get(Execution, execution_id)
    if execution is None:
        return
    statuses = set(
        (
            await session.scalars(
                select(ExecutionStep.status).where(ExecutionStep.execution_id == execution_id)
            )
        ).all()
    )
    if ExecutionStatus.FAILED.value in statuses:
        execution.status = ExecutionStatus.FAILED.value
    elif ExecutionStatus.AWAITING_APPROVAL.value in statuses:
        execution.status = ExecutionStatus.AWAITING_APPROVAL.value
    else:
        execution.status = ExecutionStatus.COMPLETED.value
