import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

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


class CalendarAgent:
    supported_operations = {
        "search_events",
        "get_event",
        "create_event",
        "update_event",
        "delete_event",
    }

    def __init__(self, clients: GoogleClientFactory) -> None:
        self._clients = clients

    async def search(self, query: StructuredData) -> AgentResult:
        return await self.search_events(query)

    async def get_context(self, request: StructuredData) -> AgentResult:
        return await self.get_event(request)

    async def execute(self, operation: str, arguments: StructuredData) -> AgentResult:
        operations = {
            "search_events": self.search_events,
            "get_event": self.get_event,
            "create_event": self.create_event,
            "update_event": self.update_event,
            "delete_event": self.delete_event,
        }
        handler = operations.get(operation)
        if handler is None:
            raise ValueError(f"Unsupported Calendar operation: {operation}")
        return await safely_execute(handler, arguments)

    async def search_events(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("calendar", "v3")
        request = service.events().list(
            calendarId=optional_string(arguments, "calendar_id") or "primary",
            timeMin=_optional_aware_timestamp(arguments, "time_min"),
            timeMax=_optional_aware_timestamp(arguments, "time_max"),
            q=optional_string(arguments, "keywords"),
            singleEvents=True,
            orderBy="startTime",
            maxResults=bounded_int(arguments, "max_results", 20, 250),
        )
        response = await asyncio.to_thread(request.execute)
        attendee = optional_string(arguments, "attendee")
        events = [_event_summary(event) for event in response.get("items", [])]
        if attendee:
            events = [
                event
                for event in events
                if attendee.lower()
                in {str(item).lower() for item in event.get("attendees", [])}
            ]
        return completed(
            {"events": events, "next_page_token": response.get("nextPageToken")},
            [str(event["id"]) for event in events],
        )

    async def get_event(self, arguments: StructuredData) -> AgentResult:
        event_id = require_string(arguments, "event_id")
        service = await self._clients.build("calendar", "v3")
        event = await asyncio.to_thread(
            service.events()
            .get(
                calendarId=optional_string(arguments, "calendar_id") or "primary",
                eventId=event_id,
            )
            .execute
        )
        return completed({"event": _event_summary(event)}, [event_id])

    async def create_event(self, arguments: StructuredData) -> AgentResult:
        service = await self._clients.build("calendar", "v3")
        body = _event_body(arguments, require_times=True)
        create_google_meet = arguments.get("create_google_meet") is True
        if create_google_meet:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
        insert_arguments: dict[str, Any] = {
            "calendarId": optional_string(arguments, "calendar_id") or "primary",
            "body": body,
            "sendUpdates": "all",
        }
        if create_google_meet:
            insert_arguments["conferenceDataVersion"] = 1
        event = await asyncio.to_thread(
            service.events().insert(**insert_arguments).execute
        )
        return completed({"event": _event_summary(event)}, [str(event["id"])])

    async def update_event(self, arguments: StructuredData) -> AgentResult:
        event_id = require_string(arguments, "event_id")
        service = await self._clients.build("calendar", "v3")
        body = _event_body(arguments, require_times=False)
        event = await asyncio.to_thread(
            service.events()
            .patch(
                calendarId=optional_string(arguments, "calendar_id") or "primary",
                eventId=event_id,
                body=body,
                sendUpdates="all",
            )
            .execute
        )
        return completed({"event": _event_summary(event)}, [event_id])

    async def delete_event(self, arguments: StructuredData) -> AgentResult:
        event_id = require_string(arguments, "event_id")
        service = await self._clients.build("calendar", "v3")
        await asyncio.to_thread(
            service.events()
            .delete(
                calendarId=optional_string(arguments, "calendar_id") or "primary",
                eventId=event_id,
                sendUpdates="all",
            )
            .execute
        )
        return completed({"event_id": event_id, "deleted": True}, [event_id])


def _event_body(arguments: StructuredData, require_times: bool) -> dict[str, Any]:
    body: dict[str, Any] = {}
    title = require_string(arguments, "title") if require_times else optional_string(arguments, "title")
    start = (
        _required_aware_timestamp(arguments, "start")
        if require_times
        else _optional_aware_timestamp(arguments, "start")
    )
    end = (
        _required_aware_timestamp(arguments, "end")
        if require_times
        else _optional_aware_timestamp(arguments, "end")
    )
    timezone_name = optional_string(arguments, "timezone")
    if title:
        body["summary"] = title
    if start:
        body["start"] = {"dateTime": start, **({"timeZone": timezone_name} if timezone_name else {})}
    if end:
        body["end"] = {"dateTime": end, **({"timeZone": timezone_name} if timezone_name else {})}
    description = optional_string(arguments, "description")
    if description is not None:
        body["description"] = description
    attendees = string_list(arguments, "attendees")
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]
    if not body:
        raise ValueError("At least one event field must be supplied")
    return body


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "title": event.get("summary", ""),
        "description": event.get("description", ""),
        "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
        "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
        "timezone": event.get("start", {}).get("timeZone"),
        "attendees": [item.get("email") for item in event.get("attendees", []) if item.get("email")],
        "html_link": event.get("htmlLink"),
        "status": event.get("status"),
        "meet_url": event.get("hangoutLink"),
        "conference_data": event.get("conferenceData"),
    }


def _required_aware_timestamp(arguments: StructuredData, name: str) -> str:
    value = require_string(arguments, name)
    _validate_aware_timestamp(value, name)
    return value


def _optional_aware_timestamp(arguments: StructuredData, name: str) -> str | None:
    value = optional_string(arguments, name)
    if value is not None:
        _validate_aware_timestamp(value, name)
    return value


def _validate_aware_timestamp(value: str, name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
