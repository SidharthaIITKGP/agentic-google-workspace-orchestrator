import json

import pytest
from pydantic import ValidationError

from app.schemas import (
    AgentResult,
    ExecutionPlan,
    ExecutionStatus,
    ExecutionStep,
    Intent,
    Service,
    StepResult,
)


def make_step(
    step_id: str,
    *,
    depends_on: list[str] | None = None,
    arguments: dict[str, object] | None = None,
) -> ExecutionStep:
    return ExecutionStep(
        step_id=step_id,
        service=Service.GMAIL,
        operation="search_messages",
        arguments=arguments or {},
        depends_on=depends_on or [],
    )


def test_plan_supports_independent_steps() -> None:
    plan = ExecutionPlan(steps=[make_step("mail"), make_step("calendar")])

    assert [step.step_id for step in plan.steps] == ["mail", "calendar"]
    assert all(not step.depends_on for step in plan.steps)


def test_plan_supports_sequential_steps_and_output_references() -> None:
    plan = ExecutionPlan(
        steps=[
            make_step("find_message"),
            make_step(
                "use_message",
                depends_on=["find_message"],
                arguments={
                    "message_id": {"$step": "find_message", "path": ["messages", 0, "id"]}
                },
            ),
        ]
    )

    assert plan.steps[1].depends_on == ["find_message"]


@pytest.mark.parametrize(
    "steps",
    [
        [make_step("first"), make_step("first")],
        [make_step("first", depends_on=["missing"])],
        [make_step("first", depends_on=["first"])],
    ],
)
def test_plan_rejects_invalid_dependencies(steps: list[ExecutionStep]) -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(steps=steps)


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        ExecutionPlan(
            steps=[
                make_step("first", depends_on=["second"]),
                make_step("second", depends_on=["first"]),
            ]
        )


def test_plan_rejects_malformed_or_unbound_output_references() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            steps=[
                make_step("first"),
                make_step("second", arguments={"value": {"$step": "first", "path": "bad"}}),
            ]
        )

    with pytest.raises(ValidationError, match="must depend on referenced step"):
        ExecutionPlan(
            steps=[
                make_step("first"),
                make_step("second", arguments={"value": {"$step": "first"}}),
            ]
        )

    with pytest.raises(ValidationError, match="references nonexistent step"):
        ExecutionPlan(
            steps=[
                make_step(
                    "first",
                    depends_on=[],
                    arguments={"value": {"$step": "missing"}},
                )
            ]
        )


def test_contracts_serialize_to_json() -> None:
    intent = Intent(
        intent_name="find_project_files",
        required_services=[Service.GOOGLE_DRIVE],
        extracted_entities={"project": "apollo"},
    )
    step_result = StepResult(
        step_id="drive_search",
        status=ExecutionStatus.COMPLETED,
        data={"file_ids": ["file-1"]},
    )
    agent_result = AgentResult(
        status=ExecutionStatus.COMPLETED,
        data={"files": [{"id": "file-1"}]},
        source_ids=["file-1"],
    )
    plan = ExecutionPlan(
        steps=[
            make_step("drive_search"),
            make_step(
                "use_file",
                depends_on=["drive_search"],
                arguments={"file_id": {"$step": "drive_search", "path": ["file_ids", 0]}},
            ),
        ]
    )

    payload = json.loads(
        json.dumps(
            {
                "intent": intent.model_dump(mode="json"),
                "step_result": step_result.model_dump(mode="json"),
                "agent_result": agent_result.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
            }
        )
    )

    assert payload["intent"]["required_services"] == ["google_drive"]
    assert payload["step_result"]["status"] == "completed"
    assert payload["agent_result"]["source_ids"] == ["file-1"]
    assert payload["plan"]["steps"][1]["arguments"]["file_id"]["$step"] == "drive_search"


def test_structured_inputs_reject_non_json_values() -> None:
    with pytest.raises(ValidationError):
        make_step("invalid", arguments={"value": object()})
