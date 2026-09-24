import asyncio
from uuid import uuid4

from app.db.models import ActionApproval, Execution
from app.orchestration.executor import DAGExecutor
from app.schemas.contracts import (
    AgentResult,
    ErrorInfo,
    ExecutionPlan,
    ExecutionStatus,
    ExecutionStep,
    Intent,
    Service,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, value: object) -> None:
        if hasattr(value, "id") and getattr(value, "id") is None:
            setattr(value, "id", uuid4())
        self.added.append(value)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.active = 0
        self.peak_active = 0

    def validate_plan(self, plan) -> None:
        pass

    def requires_approval(self, service, operation) -> bool:
        return operation == "send_email"

    async def execute(self, service, operation, arguments):
        self.calls.append((operation, arguments))
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if operation == "fail":
            return AgentResult(
                status=ExecutionStatus.FAILED,
                error=ErrorInfo(code="failed", message="failed"),
            )
        if operation == "produce":
            return AgentResult(status=ExecutionStatus.COMPLETED, data={"value": "resolved"})
        return AgentResult(
            status=ExecutionStatus.COMPLETED,
            data={"arguments": arguments},
        )


INTENT = Intent(intent_name="test", required_services=[Service.GMAIL])


def run_plan(plan: ExecutionPlan, registry: FakeRegistry | None = None):
    async def exercise():
        active_registry = registry or FakeRegistry()
        session = FakeSession()
        outcome = await DAGExecutor(session, active_registry).execute(
            uuid4(), uuid4(), INTENT, plan
        )
        return outcome, session, active_registry

    return asyncio.run(exercise())


def test_executor_runs_independent_steps_in_parallel() -> None:
    plan = ExecutionPlan(
        steps=[
            ExecutionStep(step_id="one", service=Service.GMAIL, operation="first"),
            ExecutionStep(step_id="two", service=Service.GMAIL, operation="second"),
        ]
    )

    outcome, _, registry = run_plan(plan)

    assert registry.peak_active == 2
    assert all(result.status == ExecutionStatus.COMPLETED for result in outcome.results)


def test_executor_resolves_dependency_references() -> None:
    plan = ExecutionPlan(
        steps=[
            ExecutionStep(step_id="source", service=Service.GMAIL, operation="produce"),
            ExecutionStep(
                step_id="consumer",
                service=Service.GMAIL,
                operation="consume",
                depends_on=["source"],
                arguments={"input": {"$step": "source", "path": ["value"]}},
            ),
        ]
    )

    _, _, registry = run_plan(plan)

    assert registry.calls[-1] == ("consume", {"input": "resolved"})


def test_executor_preserves_unrelated_success_after_partial_failure() -> None:
    plan = ExecutionPlan(
        steps=[
            ExecutionStep(step_id="failed", service=Service.GMAIL, operation="fail"),
            ExecutionStep(step_id="independent", service=Service.GMAIL, operation="ok"),
            ExecutionStep(
                step_id="dependent",
                service=Service.GMAIL,
                operation="consume",
                depends_on=["failed"],
            ),
        ]
    )

    outcome, _, _ = run_plan(plan)
    statuses = {result.step_id: result.status for result in outcome.results}

    assert statuses == {
        "failed": ExecutionStatus.FAILED,
        "independent": ExecutionStatus.COMPLETED,
        "dependent": ExecutionStatus.SKIPPED,
    }


def test_executor_gates_consequential_action_for_approval() -> None:
    registry = FakeRegistry()
    plan = ExecutionPlan(
        steps=[
            ExecutionStep(
                step_id="send",
                service=Service.GMAIL,
                operation="send_email",
                arguments={"draft_id": "draft-1"},
            )
        ]
    )

    outcome, session, _ = run_plan(plan, registry)

    assert outcome.results[0].status == ExecutionStatus.AWAITING_APPROVAL
    assert registry.calls == []
    assert any(isinstance(item, ActionApproval) for item in session.added)
    assert any(isinstance(item, Execution) for item in session.added)
