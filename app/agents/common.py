from collections.abc import Awaitable, Callable
from typing import Any

from googleapiclient.errors import HttpError

from app.schemas.contracts import AgentResult, ErrorInfo, ExecutionStatus, StructuredData

Operation = Callable[[StructuredData], Awaitable[AgentResult]]


def completed(data: StructuredData, source_ids: list[str] | None = None) -> AgentResult:
    return AgentResult(
        status=ExecutionStatus.COMPLETED,
        data=data,
        source_ids=source_ids or [],
    )


def failed(code: str, message: str) -> AgentResult:
    return AgentResult(
        status=ExecutionStatus.FAILED,
        error=ErrorInfo(code=code, message=message),
    )


async def safely_execute(operation: Operation, arguments: StructuredData) -> AgentResult:
    try:
        return await operation(arguments)
    except HttpError as exc:
        status_code = getattr(exc.resp, "status", None)
        code = "resource_not_found" if status_code == 404 else "google_api_error"
        return failed(code, "The Google service request could not be completed")
    except (KeyError, TypeError, ValueError) as exc:
        return failed("invalid_arguments", str(exc))


def require_string(arguments: StructuredData, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def optional_string(arguments: StructuredData, name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip() or None


def string_list(arguments: StructuredData, name: str) -> list[str]:
    value = arguments.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings")
    return value


def bounded_int(arguments: StructuredData, name: str, default: int, maximum: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return min(value, maximum)
