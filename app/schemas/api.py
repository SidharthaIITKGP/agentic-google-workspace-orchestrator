from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.contracts import Intent


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRequest(ApiModel):
    query: str = Field(min_length=1, max_length=10_000)
    conversation_id: UUID | None = None


class QueryResponse(ApiModel):
    response: str
    conversation_id: UUID
    execution_id: UUID | None = None
    intent: Intent
    actions_taken: list[dict[str, JsonValue]] = Field(default_factory=list)
    pending_approvals: list[dict[str, JsonValue]] = Field(default_factory=list)
    errors: list[dict[str, JsonValue]] = Field(default_factory=list)


class ApprovalResponse(ApiModel):
    approval_id: UUID
    status: str
    result: dict[str, JsonValue] | None = None


class SyncTriggerResponse(ApiModel):
    status: str
    task_id: str


class SyncServiceStatus(ApiModel):
    service: str
    status: str
    last_attempted_sync: str | None = None
    last_successful_sync: str | None = None
    error: dict[str, JsonValue] | None = None


class SyncStatusResponse(ApiModel):
    services: list[SyncServiceStatus]
