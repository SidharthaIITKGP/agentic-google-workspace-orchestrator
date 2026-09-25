import asyncio
from typing import Any

from app.agents.common import (
    bounded_int,
    completed,
    optional_string,
    require_string,
    safely_execute,
)
from app.integrations.google import GoogleClientFactory
from app.schemas.contracts import AgentResult, StructuredData

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"


class DriveAgent:
    supported_operations = {
        "search_files",
        "get_file",
        "share_file",
        "create_folder",
        "move_file",
    }

    def __init__(self, clients: GoogleClientFactory) -> None:
        self._clients = clients

    async def search(self, query: StructuredData) -> AgentResult:
        return await self.search_files(query)

    async def get_context(self, request: StructuredData) -> AgentResult:
        return await self.get_file(request)

    async def execute(self, operation: str, arguments: StructuredData) -> AgentResult:
        operations = {
            "search_files": self.search_files,
            "get_file": self.get_file,
            "share_file": self.share_file,
            "create_folder": self.create_folder,
            "move_file": self.move_file,
        }
        handler = operations.get(operation)
        if handler is None:
            raise ValueError(f"Unsupported Drive operation: {operation}")
        return await safely_execute(handler, arguments)

    async def search_files(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("drive", "v3")
        query_parts = ["trashed = false"]
        filename = optional_string(arguments, "filename")
        mime_type = optional_string(arguments, "mime_type")
        modified_after = optional_string(arguments, "modified_after")
        modified_before = optional_string(arguments, "modified_before")
        if filename:
            query_parts.append(f"name contains '{_escape_query(filename)}'")
        if mime_type:
            query_parts.append(f"mimeType = '{_escape_query(mime_type)}'")
        if modified_after:
            query_parts.append(f"modifiedTime >= '{_escape_query(modified_after)}'")
        if modified_before:
            query_parts.append(f"modifiedTime < '{_escape_query(modified_before)}'")
        response = await asyncio.to_thread(
            service.files()
            .list(
                q=" and ".join(query_parts),
                orderBy="modifiedTime desc",
                pageSize=bounded_int(arguments, "max_results", 50, 100),
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,parents,webViewLink,size)",
            )
            .execute
        )
        files = response.get("files", [])
        return completed(
            {"files": files, "next_page_token": response.get("nextPageToken")},
            [str(file["id"]) for file in files],
        )

    async def get_file(self, arguments: StructuredData) -> AgentResult:
        file_id = require_string(arguments, "file_id")
        service = await self._clients.build("drive", "v3")
        file = await asyncio.to_thread(
            service.files()
            .get(
                fileId=file_id,
                fields="id,name,mimeType,modifiedTime,createdTime,parents,webViewLink,size,description",
            )
            .execute
        )
        data: dict[str, Any] = {"file": file}
        if file.get("mimeType") == GOOGLE_DOC_MIME_TYPE:
            exported = await asyncio.to_thread(
                service.files().export(fileId=file_id, mimeType="text/plain").execute
            )
            data["text"] = exported.decode("utf-8", errors="replace") if isinstance(exported, bytes) else str(exported)
        return completed(data, [file_id])

    async def share_file(self, arguments: StructuredData) -> AgentResult:
        file_id = require_string(arguments, "file_id")
        email = require_string(arguments, "email")
        role = optional_string(arguments, "role") or "reader"
        if role not in {"reader", "commenter", "writer"}:
            raise ValueError("role must be reader, commenter, or writer")
        service = await self._clients.build("drive", "v3")
        permission = await asyncio.to_thread(
            service.permissions()
            .create(
                fileId=file_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=True,
                fields="id,type,role,emailAddress",
            )
            .execute
        )
        return completed({"file_id": file_id, "permission": permission}, [file_id])

    async def create_folder(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("drive", "v3")
        body: dict[str, Any] = {
            "name": require_string(arguments, "name"),
            "mimeType": FOLDER_MIME_TYPE,
        }
        parent_id = optional_string(arguments, "parent_id")
        if parent_id:
            body["parents"] = [parent_id]
        folder = await asyncio.to_thread(
            service.files().create(body=body, fields="id,name,mimeType,parents,webViewLink").execute
        )
        return completed({"folder": folder}, [str(folder["id"])])

    async def move_file(self, arguments: StructuredData) -> AgentResult:
        file_id = require_string(arguments, "file_id")
        destination_id = require_string(arguments, "destination_folder_id")
        service = await self._clients.build("drive", "v3")
        current = await asyncio.to_thread(
            service.files().get(fileId=file_id, fields="parents").execute
        )
        previous_parents = ",".join(current.get("parents", []))
        moved = await asyncio.to_thread(
            service.files()
            .update(
                fileId=file_id,
                addParents=destination_id,
                removeParents=previous_parents or None,
                fields="id,name,parents,webViewLink",
            )
            .execute
        )
        return completed({"file": moved}, [file_id])


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")
