import asyncio
import base64
from email.mime.text import MIMEText
from typing import Any

from app.agents.common import (
    bounded_int,
    completed,
    optional_string,
    require_string,
    safely_execute,
    string_list,
)
from app.integrations.google import GoogleClientFactory
from app.schemas.contracts import AgentResult, StructuredData


class GmailAgent:
    supported_operations = {
        "search_emails",
        "get_email",
        "draft_email",
        "send_email",
        "update_labels",
    }

    def __init__(self, clients: GoogleClientFactory) -> None:
        self._clients = clients

    async def search(self, query: StructuredData) -> AgentResult:
        return await self.search_emails(query)

    async def get_context(self, request: StructuredData) -> AgentResult:
        return await self.get_email(request)

    async def execute(self, operation: str, arguments: StructuredData) -> AgentResult:
        operations = {
            "search_emails": self.search_emails,
            "get_email": self.get_email,
            "draft_email": self.draft_email,
            "send_email": self.send_email,
            "update_labels": self.update_labels,
        }
        handler = operations.get(operation)
        if handler is None:
            raise ValueError(f"Unsupported Gmail operation: {operation}")
        return await safely_execute(handler, arguments)

    async def search_emails(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("gmail", "v1")
        query_parts: list[str] = []
        sender = optional_string(arguments, "sender")
        keywords = optional_string(arguments, "keywords")
        date_from = optional_string(arguments, "date_from")
        date_to = optional_string(arguments, "date_to")
        if sender:
            query_parts.append(f"from:{sender}")
        if keywords:
            query_parts.append(keywords)
        if date_from:
            query_parts.append(f"after:{date_from.replace('-', '/')}")
        if date_to:
            query_parts.append(f"before:{date_to.replace('-', '/')}")
        max_results = bounded_int(arguments, "max_results", 20, 100)
        response = await asyncio.to_thread(
            service.users()
            .messages()
            .list(userId="me", q=" ".join(query_parts), maxResults=max_results)
            .execute
        )
        messages: list[dict[str, Any]] = []
        for item in response.get("messages", []):
            message = await asyncio.to_thread(
                service.users()
                .messages()
                .get(userId="me", id=item["id"], format="metadata")
                .execute
            )
            messages.append(_parse_message(message, include_body=False))
        return completed(
            {"emails": messages, "next_page_token": response.get("nextPageToken")},
            [message["id"] for message in messages],
        )

    async def get_email(self, arguments: StructuredData) -> AgentResult:
        message_id = require_string(arguments, "message_id")
        service = await self._clients.build("gmail", "v1")
        message = await asyncio.to_thread(
            service.users().messages().get(userId="me", id=message_id, format="full").execute
        )
        return completed({"email": _parse_message(message, include_body=True)}, [message_id])

    async def draft_email(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("gmail", "v1")
        raw = _encoded_message(arguments)
        result = await asyncio.to_thread(
            service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute
        )
        draft_id = str(result["id"])
        return completed({"draft_id": draft_id, "message_id": result.get("message", {}).get("id")}, [draft_id])

    async def send_email(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("gmail", "v1")
        draft_id = optional_string(arguments, "draft_id")
        if draft_id:
            result = await asyncio.to_thread(
                service.users().drafts().send(userId="me", body={"id": draft_id}).execute
            )
        else:
            result = await asyncio.to_thread(
                service.users()
                .messages()
                .send(userId="me", body={"raw": _encoded_message(arguments)})
                .execute
            )
        message_id = str(result["id"])
        return completed({"message_id": message_id, "thread_id": result.get("threadId")}, [message_id])

    async def update_labels(self, arguments: StructuredData) -> AgentResult:
        message_id = require_string(arguments, "message_id")
        service = await self._clients.build("gmail", "v1")
        result = await asyncio.to_thread(
            service.users()
            .messages()
            .modify(
                userId="me",
                id=message_id,
                body={
                    "addLabelIds": string_list(arguments, "add_label_ids"),
                    "removeLabelIds": string_list(arguments, "remove_label_ids"),
                },
            )
            .execute
        )
        return completed({"message_id": result["id"], "label_ids": result.get("labelIds", [])}, [message_id])


def _encoded_message(arguments: StructuredData) -> str:
    recipient = require_string(arguments, "to")
    subject = require_string(arguments, "subject")
    body = require_string(arguments, "body")
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = recipient
    message["subject"] = subject
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _parse_message(message: dict[str, Any], include_body: bool) -> dict[str, Any]:
    payload = message.get("payload", {})
    headers = {
        header.get("name", "").lower(): header.get("value", "")
        for header in payload.get("headers", [])
    }
    parsed = {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "date": headers.get("date", ""),
        "preview": message.get("snippet", ""),
        "label_ids": message.get("labelIds", []),
    }
    if include_body:
        parsed["body"] = _extract_text(payload)
    return parsed


def _extract_text(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        encoded = payload["body"]["data"]
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode(
            "utf-8", errors="replace"
        )
    for part in payload.get("parts", []):
        text = _extract_text(part)
        if text:
            return text
    return ""
