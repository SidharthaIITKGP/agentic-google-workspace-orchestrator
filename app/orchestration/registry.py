from app.agents.calendar import CalendarAgent
from app.agents.drive import DriveAgent
from app.agents.gmail import GmailAgent
from app.agents.workspace import WorkspaceSearchAgent
from app.orchestration.operation_specs import (
    planner_operation_catalog,
    validate_operation_arguments,
)
from app.schemas.contracts import AgentResult, ExecutionPlan, Service, StructuredData

APPROVAL_REQUIRED_OPERATIONS = {
    (Service.GMAIL, "send_email"),
    (Service.GMAIL, "update_labels"),
    (Service.GOOGLE_CALENDAR, "create_event"),
    (Service.GOOGLE_CALENDAR, "update_event"),
    (Service.GOOGLE_CALENDAR, "delete_event"),
    (Service.GOOGLE_DRIVE, "share_file"),
    (Service.GOOGLE_DRIVE, "create_folder"),
    (Service.GOOGLE_DRIVE, "move_file"),
}


class UnknownOperationError(ValueError):
    pass


class AgentRegistry:
    def __init__(
        self,
        gmail: GmailAgent,
        calendar: CalendarAgent,
        drive: DriveAgent,
        workspace: WorkspaceSearchAgent | None = None,
    ) -> None:
        self._agents = {
            Service.GMAIL: gmail,
            Service.GOOGLE_CALENDAR: calendar,
            Service.GOOGLE_DRIVE: drive,
        }
        self._operations = {
            Service.GMAIL: frozenset(gmail.supported_operations),
            Service.GOOGLE_CALENDAR: frozenset(calendar.supported_operations),
            Service.GOOGLE_DRIVE: frozenset(drive.supported_operations),
        }
        if workspace is not None:
            self._agents[Service.WORKSPACE] = workspace
            self._operations[Service.WORKSPACE] = frozenset(workspace.supported_operations)

    def validate_operation(self, service: Service, operation: str) -> None:
        if operation not in self._operations.get(service, frozenset()):
            raise UnknownOperationError(f"Unsupported operation: {service.value}.{operation}")

    def validate_plan(self, plan: ExecutionPlan) -> None:
        for step in plan.steps:
            self.validate_operation(step.service, step.operation)
            validate_operation_arguments(
                step.service,
                step.operation,
                step.arguments,
                allow_step_references=True,
            )

    def requires_approval(self, service: Service, operation: str) -> bool:
        self.validate_operation(service, operation)
        return (service, operation) in APPROVAL_REQUIRED_OPERATIONS

    async def execute(
        self,
        service: Service,
        operation: str,
        arguments: StructuredData,
    ) -> AgentResult:
        self.validate_operation(service, operation)
        validate_operation_arguments(service, operation, arguments)
        return await self._agents[service].execute(operation, arguments)

    def prompt_catalog(self) -> dict[str, dict[str, dict[str, object]]]:
        return planner_operation_catalog()
