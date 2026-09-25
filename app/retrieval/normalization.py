import base64
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedWorkspaceItem:
    service: str
    external_resource_id: str
    title: str
    searchable_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None


def normalize_gmail(message: dict[str, Any]) -> NormalizedWorkspaceItem:
    payload = message.get("payload") or {}
    headers = {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in payload.get("headers", [])
    }
    subject = headers.get("subject") or "(no subject)"
    body = _gmail_text(payload) or str(message.get("snippet") or "")
    body = body[:50_000]
    sender = headers.get("from", "")
    recipients = headers.get("to", "")
    raw_date = headers.get("date", "")
    sent_at = _email_datetime(raw_date)
    text = _labeled_text(
        Subject=subject,
        Sender=sender,
        Recipients=recipients,
        Date=sent_at,
        Body=body,
    )
    return NormalizedWorkspaceItem(
        service="gmail",
        external_resource_id=str(message["id"]),
        title=subject,
        searchable_text=text,
        metadata={
            "sender": sender,
            "recipients": recipients,
            "date": sent_at,
            "thread_id": message.get("threadId"),
            "label_ids": message.get("labelIds", []),
        },
    )


def normalize_calendar(event: dict[str, Any]) -> NormalizedWorkspaceItem:
    title = str(event.get("summary") or "(untitled event)")
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date") or ""
    end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
    attendees = [
        str(item.get("email"))
        for item in event.get("attendees", [])
        if item.get("email")
    ]
    description = str(event.get("description") or "")[:20_000]
    return NormalizedWorkspaceItem(
        service="google_calendar",
        external_resource_id=str(event["id"]),
        title=title,
        searchable_text=_labeled_text(
            Title=title,
            Description=description,
            Start=str(start),
            End=str(end),
            Attendees=", ".join(attendees),
        ),
        metadata={
            "start": start,
            "end": end,
            "attendees": attendees,
            "status": event.get("status"),
        },
        source_created_at=_parse_datetime(event.get("created")),
        source_updated_at=_parse_datetime(event.get("updated")),
    )


def normalize_drive(file: dict[str, Any], text_content: str | None = None) -> NormalizedWorkspaceItem:
    title = str(file.get("name") or "(unnamed file)")
    mime_type = str(file.get("mimeType") or "")
    description = str(file.get("description") or "")
    safe_text = (text_content or "")[:100_000]
    return NormalizedWorkspaceItem(
        service="google_drive",
        external_resource_id=str(file["id"]),
        title=title,
        searchable_text=_labeled_text(
            Filename=title,
            MIMEType=mime_type,
            Description=description,
            Modified=str(file.get("modifiedTime") or ""),
            Content=safe_text,
        ),
        metadata={
            "mime_type": mime_type,
            "modified_time": file.get("modifiedTime"),
            "created_time": file.get("createdTime"),
            "parents": file.get("parents", []),
            "web_view_link": file.get("webViewLink"),
        },
        source_created_at=_parse_datetime(file.get("createdTime")),
        source_updated_at=_parse_datetime(file.get("modifiedTime")),
    )


def _gmail_text(payload: dict[str, Any]) -> str:
    if payload.get("mimeType") == "text/plain":
        encoded = payload.get("body", {}).get("data")
        if encoded:
            try:
                return base64.urlsafe_b64decode(
                    str(encoded) + "=" * (-len(str(encoded)) % 4)
                ).decode("utf-8", errors="replace")
            except (ValueError, TypeError):
                return ""
    for part in payload.get("parts", []):
        text = _gmail_text(part)
        if text:
            return text
    return ""


def _labeled_text(**fields: str) -> str:
    return "\n".join(f"{name}: {value}" for name, value in fields.items() if value)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _email_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value
