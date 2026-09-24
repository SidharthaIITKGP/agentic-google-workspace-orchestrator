from app.agents.calendar import CalendarAgent
from app.agents.drive import DriveAgent
from app.agents.gmail import GmailAgent
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

    def validate_operation(self, service: Service, operation: str) -> None:
        if operation not in self._operations.get(service, frozenset()):
            raise UnknownOperationError(f"Unsupported operation: {service.value}.{operation}")

    def validate_plan(self, plan: ExecutionPlan) -> None:
        for step in plan.steps:
            self.validate_operation(step.service, step.operation)

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
        return await self._agents[service].execute(operation, arguments)

    def prompt_catalog(self) -> dict[str, list[str]]:
        return {
            service.value: sorted(operations)
            for service, operations in self._operations.items()
        }
