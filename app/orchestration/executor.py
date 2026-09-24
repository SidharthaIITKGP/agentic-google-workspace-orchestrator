import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ActionApproval,
    Execution,
    ExecutionStep as ExecutionStepRecord,
)
from app.orchestration.registry import AgentRegistry
from app.schemas.contracts import (
    AgentResult,
    ErrorInfo,
    ExecutionPlan,
    ExecutionStatus,
    ExecutionStep,
    Intent,
    StepResult,
    StructuredData,
)


@dataclass(frozen=True)
class ExecutionOutcome:
    execution_id: UUID
    results: list[StepResult]
    pending_approval_ids: list[UUID]


class DAGExecutor:
    def __init__(self, session: AsyncSession, registry: AgentRegistry) -> None:
        self._session = session
        self._registry = registry

    async def execute(
        self,
        user_id: UUID,
        conversation_id: UUID,
        intent: Intent,
        plan: ExecutionPlan,
    ) -> ExecutionOutcome:
        self._registry.validate_plan(plan)
        execution = Execution(
            user_id=user_id,
            conversation_id=conversation_id,
            status=ExecutionStatus.RUNNING.value,
            intent=intent.model_dump(mode="json"),
            execution_plan=plan.model_dump(mode="json"),
        )
        self._session.add(execution)
        await self._session.flush()

        remaining = {step.step_id: step for step in plan.steps}
        results: dict[str, StepResult] = {}
        approval_ids: list[UUID] = []

        while remaining:
            ready = [
                step
                for step in remaining.values()
                if all(dependency in results for dependency in step.depends_on)
            ]
            if not ready:
                raise RuntimeError("Execution plan has no runnable steps")

            executable: list[tuple[ExecutionStep, StructuredData]] = []
            wave_results: list[
                tuple[ExecutionStep, StepResult, UUID | None, StructuredData]
            ] = []
            for step in ready:
                dependency_failed = any(
                    results[dependency].status
                    in {
                        ExecutionStatus.FAILED,
                        ExecutionStatus.SKIPPED,
                        ExecutionStatus.AWAITING_APPROVAL,
                    }
                    for dependency in step.depends_on
                )
                if dependency_failed:
                    wave_results.append(
                        (
                            step,
                            StepResult(
                                step_id=step.step_id,
                                status=ExecutionStatus.SKIPPED,
                                error=ErrorInfo(
                                    code="dependency_unavailable",
                                    message="A required prior step did not complete",
                                ),
                            ),
                            None,
                            step.arguments,
                        )
                    )
                    continue
                try:
                    arguments = _resolve_references(step.arguments, results)
                except (KeyError, IndexError, TypeError, ValueError):
                    wave_results.append(
                        (
                            step,
                            StepResult(
                                step_id=step.step_id,
                                status=ExecutionStatus.FAILED,
                                error=ErrorInfo(
                                    code="reference_resolution_failed",
                                    message="A prior step output reference could not be resolved",
                                ),
                            ),
                            None,
                            step.arguments,
                        )
                    )
                    continue

                if self._registry.requires_approval(step.service, step.operation):
                    approval = ActionApproval(
                        execution_id=execution.id,
                        step_id=step.step_id,
                        user_id=user_id,
                        status=ExecutionStatus.AWAITING_APPROVAL.value,
                        proposed_action={
                            "service": step.service.value,
                            "operation": step.operation,
                            "arguments": arguments,
                        },
                    )
                    self._session.add(approval)
                    await self._session.flush()
                    wave_results.append(
                        (
                            step,
                            StepResult(
                                step_id=step.step_id,
                                status=ExecutionStatus.AWAITING_APPROVAL,
                                data={"approval_id": str(approval.id)},
                            ),
                            approval.id,
                            arguments,
                        )
                    )
                else:
                    executable.append((step, arguments))

            if executable:
                agent_results = await asyncio.gather(
                    *(
                        self._registry.execute(step.service, step.operation, arguments)
                        for step, arguments in executable
                    ),
                    return_exceptions=True,
                )
                for (step, arguments), agent_result in zip(
                    executable, agent_results, strict=True
                ):
                    wave_results.append(
                        (step, _step_result(step, agent_result), None, arguments)
                    )

            for step, result, approval_id, resolved_arguments in wave_results:
                results[step.step_id] = result
                remaining.pop(step.step_id)
                if approval_id is not None:
                    approval_ids.append(approval_id)
                self._session.add(
                    ExecutionStepRecord(
                        execution_id=execution.id,
                        step_id=step.step_id,
                        service=step.service.value,
                        operation=step.operation,
                        status=result.status.value,
                        arguments=resolved_arguments,
                        result=result.data,
                        error_details=result.error.model_dump(mode="json") if result.error else None,
                    )
                )
            await self._session.flush()

        ordered_results = [results[step.step_id] for step in plan.steps]
        statuses = {result.status for result in ordered_results}
        if ExecutionStatus.FAILED in statuses:
            execution.status = ExecutionStatus.FAILED.value
        elif ExecutionStatus.AWAITING_APPROVAL in statuses:
            execution.status = ExecutionStatus.AWAITING_APPROVAL.value
        else:
            execution.status = ExecutionStatus.COMPLETED.value
        await self._session.commit()
        return ExecutionOutcome(execution.id, ordered_results, approval_ids)


def _step_result(
    step: ExecutionStep,
    agent_result: AgentResult | BaseException,
) -> StepResult:
    if isinstance(agent_result, BaseException):
        return StepResult(
            step_id=step.step_id,
            status=ExecutionStatus.FAILED,
            error=ErrorInfo(
                code="operation_failed",
                message="The service operation could not be completed",
            ),
        )
    return StepResult(
        step_id=step.step_id,
        status=agent_result.status,
        data=agent_result.data,
        error=agent_result.error,
    )


def _resolve_references(
    value: JsonValue,
    results: dict[str, StepResult],
) -> Any:
    if isinstance(value, dict):
        if "$step" in value:
            step_id = value["$step"]
            path = value.get("path", [])
            if not isinstance(step_id, str) or not isinstance(path, list):
                raise ValueError("Malformed step reference")
            current: Any = results[step_id].data
            for segment in path:
                if isinstance(current, dict) and isinstance(segment, str):
                    current = current[segment]
                elif isinstance(current, list) and isinstance(segment, int):
                    current = current[segment]
                else:
                    raise TypeError("Reference path does not match result structure")
            return current
        return {key: _resolve_references(item, results) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_references(item, results) for item in value]
    return value
