from datetime import date, datetime
from typing import Any

from app.schemas.contracts import Service, StructuredData


OperationSpec = dict[str, Any]


OPERATION_SPECIFICATIONS: dict[Service, dict[str, OperationSpec]] = {
    Service.GMAIL: {
        "search_emails": {
            "description": "Search Gmail messages using optional sender, text, and date filters.",
            "required_arguments": {},
            "optional_arguments": {
                "sender": "email/string",
                "keywords": "string",
                "date_from": "ISO-8601 date (YYYY-MM-DD), inclusive",
                "date_to": "ISO-8601 date (YYYY-MM-DD), exclusive",
                "max_results": "integer from 1 to 100",
            },
        },
        "get_email": {
            "description": "Retrieve one Gmail message including its text body.",
            "required_arguments": {"message_id": "non-empty string"},
            "optional_arguments": {},
        },
        "draft_email": {
            "description": "Create an email draft without sending it.",
            "required_arguments": {
                "to": "email/string",
                "subject": "non-empty string",
                "body": "non-empty string",
            },
            "optional_arguments": {},
        },
        "send_email": {
            "description": "Send an existing draft_id, or provide to, subject, and body.",
            "required_arguments": {},
            "optional_arguments": {
                "draft_id": "non-empty string; alternative to message fields",
                "to": "email/string; required without draft_id",
                "subject": "non-empty string; required without draft_id",
                "body": "non-empty string; required without draft_id",
            },
        },
        "update_labels": {
            "description": "Add or remove Gmail label identifiers on a message.",
            "required_arguments": {"message_id": "non-empty string"},
            "optional_arguments": {
                "add_label_ids": "array of strings",
                "remove_label_ids": "array of strings",
            },
        },
    },
    Service.GOOGLE_CALENDAR: {
        "search_events": {
            "description": "Search calendar events within an optional bounded time range.",
            "required_arguments": {},
            "optional_arguments": {
                "time_min": "ISO-8601 timezone-aware timestamp",
                "time_max": "ISO-8601 timezone-aware timestamp",
                "keywords": "string",
                "attendee": "email/string",
                "max_results": "integer from 1 to 250",
                "calendar_id": "string",
            },
            "result_shape": {
                "events": [
                    {
                        "id": "string",
                        "title": "string",
                        "description": "string",
                        "start": "ISO-8601 timestamp",
                        "end": "ISO-8601 timestamp",
                        "organizer": "string or null",
                        "attendees": ["email/string"],
                        "status": "string",
                    }
                ],
                "next_page_token": "string or null",
            },
            "reference_examples": {
                "selected_event_context": {
                    "$step": "calendar_step_id",
                    "path": ["events", 0],
                },
                "first_event_title": {
                    "$step": "calendar_step_id",
                    "path": ["events", 0, "title"],
                },
                "first_event_attendees": {
                    "$step": "calendar_step_id",
                    "path": ["events", 0, "attendees"],
                },
            },
        },
        "get_event": {
            "description": "Retrieve one calendar event.",
            "required_arguments": {"event_id": "non-empty string"},
            "optional_arguments": {"calendar_id": "string"},
        },
        "create_event": {
            "description": "Create a calendar event; start and end must include timezones.",
            "required_arguments": {
                "title": "non-empty string",
                "start": "ISO-8601 timezone-aware timestamp",
                "end": "ISO-8601 timezone-aware timestamp",
            },
            "optional_arguments": {
                "calendar_id": "string",
                "timezone": "IANA timezone string",
                "description": "string",
                "attendees": "array of email strings",
                "create_google_meet": "boolean; true only when the user requested Google Meet",
            },
        },
        "update_event": {
            "description": "Update supplied fields on an existing calendar event.",
            "required_arguments": {"event_id": "non-empty string"},
            "optional_arguments": {
                "calendar_id": "string",
                "title": "string",
                "start": "ISO-8601 timezone-aware timestamp",
                "end": "ISO-8601 timezone-aware timestamp",
                "timezone": "IANA timezone string",
                "description": "string",
                "attendees": "array of email strings",
            },
        },
        "delete_event": {
            "description": "Delete an existing calendar event.",
            "required_arguments": {"event_id": "non-empty string"},
            "optional_arguments": {"calendar_id": "string"},
        },
    },
    Service.GOOGLE_DRIVE: {
        "search_files": {
            "description": "Search non-trashed Drive files using name, type, and modification filters.",
            "required_arguments": {},
            "optional_arguments": {
                "filename": "string",
                "mime_type": "string",
                "modified_after": "ISO-8601 timezone-aware timestamp, inclusive",
                "modified_before": "ISO-8601 timezone-aware timestamp, exclusive",
                "max_results": "integer from 1 to 100",
            },
        },
        "get_file": {
            "description": "Retrieve Drive file metadata and export Google Docs as text.",
            "required_arguments": {"file_id": "non-empty string"},
            "optional_arguments": {},
        },
        "share_file": {
            "description": "Share a Drive file with one user.",
            "required_arguments": {
                "file_id": "non-empty string",
                "email": "email/string",
            },
            "optional_arguments": {"role": "reader, commenter, or writer"},
        },
        "create_folder": {
            "description": "Create a Drive folder, optionally within a parent folder.",
            "required_arguments": {"name": "non-empty string"},
            "optional_arguments": {"parent_id": "string"},
        },
        "move_file": {
            "description": "Move a Drive file to another folder.",
            "required_arguments": {
                "file_id": "non-empty string",
                "destination_folder_id": "non-empty string",
            },
            "optional_arguments": {},
        },
    },
    Service.WORKSPACE: {
        "workspace_search": {
            "description": (
                "Read-only semantic and keyword search over the user's locally indexed "
                "Gmail, Calendar, and Drive content. Use native Google operations for "
                "exact IDs, fresh state, and all writes."
            ),
            "required_arguments": {
                "query": (
                    "non-empty search string, or one Calendar event object whose title, "
                    "description, and limited attendees form the semantic query"
                )
            },
            "optional_arguments": {
                "services": "array containing gmail, google_calendar, and/or google_drive",
                "top_k": "integer from 1 to 50; defaults to 5",
                "sender": "email/string metadata filter",
                "date_from": "ISO-8601 timezone-aware timestamp, inclusive",
                "date_to": "ISO-8601 timezone-aware timestamp, exclusive",
                "mime_type": "Drive MIME type filter",
                "attendee": "Calendar attendee email filter",
            },
        },
    },
}


_LIST_ARGUMENTS = {"add_label_ids", "remove_label_ids", "attendees", "services"}
_TIMESTAMP_ARGUMENTS = {"time_min", "time_max", "start", "end", "modified_after", "modified_before"}


def planner_operation_catalog() -> dict[str, dict[str, OperationSpec]]:
    return {
        service.value: operations
        for service, operations in OPERATION_SPECIFICATIONS.items()
    }


def validate_operation_arguments(
    service: Service,
    operation: str,
    arguments: StructuredData,
    *,
    allow_step_references: bool = False,
) -> None:
    try:
        spec = OPERATION_SPECIFICATIONS[service][operation]
    except KeyError as exc:
        raise ValueError(f"Unsupported operation: {service.value}.{operation}") from exc

    required = set(spec["required_arguments"])
    optional = set(spec["optional_arguments"])
    unknown = set(arguments) - required - optional
    if unknown:
        raise ValueError(
            f"Unsupported arguments for {service.value}.{operation}: {', '.join(sorted(unknown))}"
        )
    missing = required - set(arguments)
    if missing:
        raise ValueError(
            f"Missing arguments for {service.value}.{operation}: {', '.join(sorted(missing))}"
        )

    for name, value in arguments.items():
        if allow_step_references and _contains_step_reference(value):
            continue
        if service == Service.WORKSPACE and operation == "workspace_search" and name == "query":
            _validate_workspace_query(value)
        elif name == "max_results":
            _validate_max_results(service, operation, value)
        elif name == "top_k":
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
                raise ValueError("top_k must be between 1 and 50")
        elif name == "create_google_meet":
            if not isinstance(value, bool):
                raise ValueError("create_google_meet must be a boolean")
        elif name in _LIST_ARGUMENTS:
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise ValueError(f"{name} must be an array of non-empty strings")
        elif name in _TIMESTAMP_ARGUMENTS:
            _aware_timestamp(value, name)
        elif name in {"date_from", "date_to"}:
            if service == Service.WORKSPACE:
                _aware_timestamp(value, name)
            else:
                _iso_date(value, name)
        elif not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")

    if operation == "send_email" and "draft_id" not in arguments:
        _require(arguments, {"to", "subject", "body"}, service, operation)
    if operation == "update_event" and not (
        set(arguments) - {"event_id", "calendar_id"}
    ):
        raise ValueError("update_event requires at least one event field")
    role = arguments.get("role", "reader")
    if (
        operation == "share_file"
        and not (allow_step_references and _contains_step_reference(role))
        and role not in {"reader", "commenter", "writer"}
    ):
        raise ValueError("role must be reader, commenter, or writer")

    if service == Service.GOOGLE_CALENDAR:
        _validate_order(arguments, "time_min", "time_max")
        _validate_order(arguments, "start", "end")
    if service == Service.GOOGLE_DRIVE:
        _validate_order(arguments, "modified_after", "modified_before")
    if service == Service.GMAIL:
        _validate_date_order(arguments, "date_from", "date_to")
    if service == Service.WORKSPACE:
        services = arguments.get("services", [])
        allowed = {
            Service.GMAIL.value,
            Service.GOOGLE_CALENDAR.value,
            Service.GOOGLE_DRIVE.value,
        }
        if any(service_name not in allowed for service_name in services):
            raise ValueError("services contains an unsupported workspace service")
        _validate_order(arguments, "date_from", "date_to")


def _contains_step_reference(value: Any) -> bool:
    if isinstance(value, dict):
        if "$step" in value:
            return True
        return any(_contains_step_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_step_reference(child) for child in value)
    return False


def _validate_workspace_query(value: Any) -> None:
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, dict):
        title = value.get("title")
        description = value.get("description")
        attendees = value.get("attendees")
        if isinstance(title, str) and title.strip():
            if description is not None and not isinstance(description, str):
                raise ValueError("workspace event description must be a string")
            if attendees is not None and (
                not isinstance(attendees, list)
                or any(not isinstance(item, str) for item in attendees)
            ):
                raise ValueError("workspace event attendees must be an array of strings")
            return
    raise ValueError("query must be a non-empty string or Calendar event context")


def _require(
    arguments: StructuredData,
    required: set[str],
    service: Service,
    operation: str,
) -> None:
    missing = required - set(arguments)
    if missing:
        raise ValueError(
            f"Missing arguments for {service.value}.{operation}: {', '.join(sorted(missing))}"
        )


def _validate_max_results(service: Service, operation: str, value: Any) -> None:
    upper = 250 if service == Service.GOOGLE_CALENDAR else 100
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
        raise ValueError(f"max_results for {operation} must be between 1 and {upper}")


def _aware_timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


def _iso_date(value: Any, name: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 date") from exc


def _validate_order(arguments: StructuredData, start_name: str, end_name: str) -> None:
    if start_name in arguments and end_name in arguments:
        if _contains_step_reference(arguments[start_name]) or _contains_step_reference(
            arguments[end_name]
        ):
            return
        if _aware_timestamp(arguments[start_name], start_name) >= _aware_timestamp(
            arguments[end_name], end_name
        ):
            raise ValueError(f"{start_name} must be before {end_name}")


def _validate_date_order(arguments: StructuredData, start_name: str, end_name: str) -> None:
    if start_name in arguments and end_name in arguments:
        if _contains_step_reference(arguments[start_name]) or _contains_step_reference(
            arguments[end_name]
        ):
            return
        if _iso_date(arguments[start_name], start_name) >= _iso_date(
            arguments[end_name], end_name
        ):
            raise ValueError(f"{start_name} must be before {end_name}")
