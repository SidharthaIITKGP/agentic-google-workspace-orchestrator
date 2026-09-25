import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import SyncState
from app.integrations.google import GoogleClientFactory
from app.retrieval.indexer import WorkspaceIndexer
from app.retrieval.normalization import normalize_calendar, normalize_drive, normalize_gmail
from app.schemas.contracts import Service


SYNC_SERVICES = (Service.GMAIL, Service.GOOGLE_CALENDAR, Service.GOOGLE_DRIVE)


class WorkspaceSyncService:
    def __init__(
        self,
        session: AsyncSession,
        clients: GoogleClientFactory,
        indexer: WorkspaceIndexer,
        settings: Settings,
    ) -> None:
        self._session = session
        self._clients = clients
        self._indexer = indexer
        self._settings = settings

    async def sync_user(self, user_id: UUID) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for service in SYNC_SERVICES:
            results[service.value] = await self.sync_service(user_id, service)
        return results

    async def sync_service(self, user_id: UUID, service: Service) -> dict[str, Any]:
        if service not in SYNC_SERVICES:
            raise ValueError(f"Unsupported sync service: {service.value}")
        state = await self._state(user_id, service)
        state.status = "running"
        previous_success = state.last_successful_sync
        if (
            previous_success is not None
            and (
                previous_success.tzinfo is None
                or previous_success.utcoffset() is None
            )
        ):
            previous_success = None
        state.last_attempted_sync = datetime.now(timezone.utc)
        state.error_details = None
        await self._session.commit()
        try:
            if service == Service.GMAIL:
                count, cursor = await self._sync_gmail(
                    user_id, since=previous_success
                )
            elif service == Service.GOOGLE_CALENDAR:
                count, cursor = await self._sync_calendar(user_id)
            else:
                count, cursor = await self._sync_drive(
                    user_id, since=previous_success
                )
            state = await self._state(user_id, service)
            state.status = "completed"
            state.sync_cursor = cursor
            state.last_successful_sync = datetime.now(timezone.utc)
            state.error_details = None
            await self._session.commit()
            return {"status": "completed", "indexed_items": count}
        except Exception as exc:
            await self._session.rollback()
            state = await self._state(user_id, service)
            state.status = "failed"
            state.error_details = {"type": type(exc).__name__}
            await self._session.commit()
            return {"status": "failed", "indexed_items": 0}

    async def _sync_gmail(
        self,
        user_id: UUID,
        since: datetime | None = None,
    ) -> tuple[int, str | None]:
        gmail = await self._clients.build("gmail", "v1")
        maximum = self._settings.sync_gmail_max_items
        count = 0
        page_token: str | None = None
        while count < maximum:
            list_arguments: dict[str, Any] = {
                "userId": "me",
                "maxResults": min(100, maximum - count),
                "pageToken": page_token,
            }
            if since is not None:
                list_arguments["q"] = f"after:{int(since.timestamp())}"
            response = await asyncio.to_thread(
                gmail.users().messages().list(**list_arguments).execute
            )
            for reference in response.get("messages", []):
                message = await asyncio.to_thread(
                    gmail.users().messages().get(
                        userId="me", id=reference["id"], format="full"
                    ).execute
                )
                await self._indexer.index_item(user_id, normalize_gmail(message))
                count += 1
                if count >= maximum:
                    break
            page_token = response.get("nextPageToken")
            if not page_token or count >= maximum:
                break
        return count, page_token

    async def _sync_calendar(self, user_id: UUID) -> tuple[int, str | None]:
        calendar = await self._clients.build("calendar", "v3")
        now = datetime.now(timezone.utc)
        time_min = now - timedelta(days=self._settings.sync_calendar_lookback_days)
        time_max = now + timedelta(days=self._settings.sync_calendar_lookahead_days)
        count = 0
        page_token: str | None = None
        while True:
            response = await asyncio.to_thread(
                calendar.events().list(
                    calendarId="primary",
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                ).execute
            )
            for event in response.get("items", []):
                await self._indexer.index_item(user_id, normalize_calendar(event))
                count += 1
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return count, None

    async def _sync_drive(
        self,
        user_id: UUID,
        since: datetime | None = None,
    ) -> tuple[int, str | None]:
        drive = await self._clients.build("drive", "v3")
        maximum = self._settings.sync_drive_max_items
        count = 0
        page_token: str | None = None
        fields = (
            "nextPageToken,files(id,name,mimeType,description,modifiedTime,createdTime,"
            "parents,webViewLink,size,trashed)"
        )
        query = "trashed = false"
        if since is not None:
            query += f" and modifiedTime > '{since.astimezone(timezone.utc).isoformat()}'"
        while count < maximum:
            response = await asyncio.to_thread(
                drive.files().list(
                    q=query,
                    pageSize=min(100, maximum - count),
                    pageToken=page_token,
                    fields=fields,
                ).execute
            )
            for file in response.get("files", []):
                text_content = await self._drive_text(drive, file)
                await self._indexer.index_item(
                    user_id, normalize_drive(file, text_content=text_content)
                )
                count += 1
                if count >= maximum:
                    break
            page_token = response.get("nextPageToken")
            if not page_token or count >= maximum:
                break
        return count, page_token

    async def _drive_text(self, drive: Any, file: dict[str, Any]) -> str | None:
        mime_type = file.get("mimeType")
        if mime_type == "application/vnd.google-apps.document":
            content = await asyncio.to_thread(
                drive.files().export(fileId=file["id"], mimeType="text/plain").execute
            )
        elif mime_type == "text/plain":
            content = await asyncio.to_thread(
                drive.files().get_media(fileId=file["id"]).execute
            )
        else:
            # PDFs remain searchable by metadata; OCR/full PDF extraction is intentionally omitted.
            return None
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    async def _state(self, user_id: UUID, service: Service) -> SyncState:
        state = await self._session.scalar(
            select(SyncState).where(
                SyncState.user_id == user_id,
                SyncState.service == service.value,
            )
        )
        if state is None:
            state = SyncState(user_id=user_id, service=service.value, status="pending")
            self._session.add(state)
            await self._session.flush()
        return state
