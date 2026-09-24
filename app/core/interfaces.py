from typing import Protocol

from app.schemas.contracts import AgentResult, OperationName, StructuredData


class ServiceAgent(Protocol):
    """Common asynchronous contract for future Workspace service agents."""

    async def search(self, query: StructuredData) -> AgentResult: ...

    async def get_context(self, request: StructuredData) -> AgentResult: ...

    async def execute(
        self,
        operation: OperationName,
        arguments: StructuredData,
    ) -> AgentResult: ...
