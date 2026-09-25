from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator, model_validator

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
]
OperationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StructuredData = dict[str, JsonValue]


class Service(StrEnum):
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"
    GOOGLE_DRIVE = "google_drive"
    WORKSPACE = "workspace"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorInfo(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: StructuredData = Field(default_factory=dict)


class Intent(ContractModel):
    intent_name: str = Field(min_length=1)
    required_services: list[Service] = Field(default_factory=list)
    extracted_entities: StructuredData = Field(default_factory=dict)
    requires_clarification: bool = False
    clarification_question: str | None = None

    @field_validator("required_services")
    @classmethod
    def required_services_must_be_unique(cls, services: list[Service]) -> list[Service]:
        if len(services) != len(set(services)):
            raise ValueError("required_services must not contain duplicates")
        return services


class StepOutputReference(ContractModel):
    """A serializable pointer to data produced by an earlier plan step."""

    step_id: Identifier = Field(alias="$step")
    path: list[str | int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ExecutionStep(ContractModel):
    step_id: Identifier
    service: Service
    operation: OperationName
    arguments: StructuredData = Field(default_factory=dict)
    depends_on: list[Identifier] = Field(default_factory=list)

    @field_validator("depends_on")
    @classmethod
    def dependencies_must_be_unique(cls, dependencies: list[str]) -> list[str]:
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("depends_on must not contain duplicates")
        return dependencies


class ExecutionPlan(ContractModel):
    steps: list[ExecutionStep]

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("execution plan contains duplicate step IDs")

        steps_by_id = {step.step_id: step for step in self.steps}
        known_ids = set(steps_by_id)

        for step in self.steps:
            for dependency_id in step.depends_on:
                if dependency_id == step.step_id:
                    raise ValueError(f"step '{step.step_id}' cannot depend on itself")
                if dependency_id not in known_ids:
                    raise ValueError(
                        f"step '{step.step_id}' depends on nonexistent step '{dependency_id}'"
                    )

            for referenced_id in _find_step_references(step.arguments):
                if referenced_id not in known_ids:
                    raise ValueError(
                        f"step '{step.step_id}' references nonexistent step '{referenced_id}'"
                    )
                if referenced_id not in step.depends_on:
                    raise ValueError(
                        f"step '{step.step_id}' must depend on referenced step '{referenced_id}'"
                    )

        visit_state: dict[str, int] = {}

        def visit(step_id: str) -> None:
            state = visit_state.get(step_id, 0)
            if state == 1:
                raise ValueError("execution plan contains a dependency cycle")
            if state == 2:
                return

            visit_state[step_id] = 1
            for dependency_id in steps_by_id[step_id].depends_on:
                visit(dependency_id)
            visit_state[step_id] = 2

        for step_id in step_ids:
            visit(step_id)

        return self


class StepResult(ContractModel):
    step_id: Identifier
    status: ExecutionStatus
    data: StructuredData = Field(default_factory=dict)
    error: ErrorInfo | None = None


class AgentResult(ContractModel):
    status: ExecutionStatus
    data: StructuredData = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


def _find_step_references(value: JsonValue) -> Iterator[str]:
    if isinstance(value, dict):
        if "$step" in value:
            reference = StepOutputReference.model_validate(value)
            yield reference.step_id
            return
        for child in value.values():
            yield from _find_step_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _find_step_references(child)
