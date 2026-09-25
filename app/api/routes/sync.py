from fastapi import APIRouter
from sqlalchemy import select

from app.api.dependencies import CurrentUserId, DatabaseSession
from app.db.models import SyncState
from app.schemas.api import SyncServiceStatus, SyncStatusResponse, SyncTriggerResponse
from app.sync.service import SYNC_SERVICES
from app.workers.tasks import sync_user_task


router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


@router.post("/trigger", response_model=SyncTriggerResponse, status_code=202)
async def trigger_sync(user_id: CurrentUserId) -> SyncTriggerResponse:
    task = sync_user_task.delay(str(user_id))
    return SyncTriggerResponse(status="queued", task_id=task.id)


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> SyncStatusResponse:
    states = list(
        (
            await session.scalars(
                select(SyncState).where(SyncState.user_id == user_id)
            )
        ).all()
    )
    by_service = {state.service: state for state in states}
    return SyncStatusResponse(
        services=[
            SyncServiceStatus(
                service=service.value,
                status=by_service[service.value].status if service.value in by_service else "pending",
                last_attempted_sync=(
                    by_service[service.value].last_attempted_sync.isoformat()
                    if service.value in by_service and by_service[service.value].last_attempted_sync
                    else None
                ),
                last_successful_sync=(
                    by_service[service.value].last_successful_sync.isoformat()
                    if service.value in by_service and by_service[service.value].last_successful_sync
                    else None
                ),
                error=(
                    by_service[service.value].error_details
                    if service.value in by_service
                    else None
                ),
            )
            for service in SYNC_SERVICES
        ]
    )
