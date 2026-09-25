from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
import re
from typing import Any
from uuid import UUID

from app.agents.common import completed, safely_execute
from app.core.config import Settings

from app.retrieval.freshness import evaluate_service_freshness
from app.retrieval.search import HybridWorkspaceSearch, WorkspaceSearchFilters
from app.schemas.contracts import AgentResult, StructuredData


@dataclass(frozen=True)
class _SyncSnapshot:
    service: str
    status: str
    last_successful_sync: datetime | None


def _sync_state_freshness(
    states: dict[str, dict[str, object]], stale_after: timedelta
) -> dict[str, dict[str, object]]:
    requested_services = set(states) or {
        "gmail",
        "google_calendar",
        "google_drive",
    }
    snapshots = [
        _SyncSnapshot(
            service=service,
            status=str(values.get("status", "")),
            last_successful_sync=(
                values.get("last_successful_sync")
                if isinstance(values.get("last_successful_sync"), datetime)
                else None
            ),
        )
        for service, values in states.items()
    ]
    records = evaluate_service_freshness(
        snapshots,
        requested_services,
        now=datetime.now(timezone.utc),
        stale_after=stale_after,
    )
    return {
        service: {
            "fresh": record.fresh,
            "reason": record.reason,
            "last_successful_sync": (
                record.last_successful_sync.isoformat()
                if record.last_successful_sync is not None
                else None
            ),
        }
        for service, record in records.items()
    }


class WorkspaceSearchAgent:
    supported_operations = {"workspace_search"}

    def __init__(
        self,
        search: HybridWorkspaceSearch,
        user_id: UUID,
        settings: Settings,
        native_agents: dict[str, Any] | None = None,
    ) -> None:
        self._search = search
        self._user_id = user_id
        self._native_agents = native_agents or {}
        self._stale_after = timedelta(minutes=settings.index_stale_after_minutes)

    async def search(self, query: StructuredData) -> AgentResult:
        return await self.workspace_search(query)

    async def get_context(self, request: StructuredData) -> AgentResult:
        return await self.workspace_search(request)

    async def execute(self, operation: str, arguments: StructuredData) -> AgentResult:
        if operation != "workspace_search":
            raise ValueError(f"Unsupported workspace operation: {operation}")
        return await safely_execute(self.workspace_search, arguments)

    async def workspace_search(self, arguments: StructuredData) -> AgentResult:
        query = _contextual_query(arguments["query"])
        services = arguments.get("services")
        response = await self._search.search(
            user_id=self._user_id,
            query=query,
            top_k=int(arguments.get("top_k", 5)),
            filters=WorkspaceSearchFilters(
                services=services,
                sender=arguments.get("sender"),
                date_from=arguments.get("date_from"),
                date_to=arguments.get("date_to"),
                mime_type=arguments.get("mime_type"),
                attendee=arguments.get("attendee"),
            ),
        )
        freshness = _sync_state_freshness(response.sync_states, self._stale_after)
        index_stale = not freshness or not all(
            bool(service_state["fresh"])
            for service_state in freshness.values()
        )
        results = [result.as_dict() for result in response.results]
        fallback_performed = False
        fallback_error: dict[str, str] | None = None
        fallback_source_ids: list[str] = []
        if index_stale and not results:
            (
                native_results,
                fallback_performed,
                fallback_error,
                fallback_source_ids,
            ) = await self._native_fallback(arguments, query, services)
            results.extend(native_results)
        return completed(
            {
                "results": results,
                "searched_services": services or [
                    "gmail", "google_calendar", "google_drive"
                ],
                "retrieval_duration_ms": response.duration_ms,
                "retrieval_timing_ms": {
                    "embedding": response.embedding_duration_ms,
                    "database": response.database_duration_ms,
                    "total": response.duration_ms,
                    "embedding_cache_hit": response.embedding_cache_hit,
                    "embedding_ms": response.embedding_duration_ms,
                    "database_ms": response.database_duration_ms,
                    "total_ms": response.duration_ms,
                    "cache_hit": response.embedding_cache_hit,
                },
                "index_stale": index_stale,
                "freshness": freshness,
                "native_fallback_recommended": index_stale,
                "native_fallback_performed": fallback_performed,
                **(
                    {"native_fallback_error": fallback_error}
                    if fallback_error is not None
                    else {}
                ),
            },
            [result.external_resource_id for result in response.results]
            + fallback_source_ids,
        )

    async def _native_fallback(
        self,
        arguments: StructuredData,
        contextual_query: str,
        services: object,
    ) -> tuple[list[dict[str, Any]], bool, dict[str, str] | None, list[str]]:
        requested = services if isinstance(services, list) else []
        native_results: list[dict[str, Any]] = []
        source_ids: list[str] = []
        performed = False
        error: dict[str, str] | None = None
        for service in requested:
            agent = self._native_agents.get(str(service))
            if agent is None:
                continue
            if service == "gmail":
                operation = "search_emails"
                native_arguments: StructuredData = {
                    "keywords": _native_search_text(arguments["query"], contextual_query),
                    "max_results": 10,
                }
            elif service == "google_drive":
                operation = "search_files"
                native_arguments = {
                    "filename": _native_search_text(
                        arguments["query"], contextual_query, prefer_topic=True
                    ),
                    "max_results": 10,
                }
            else:
                continue
            result = await agent.execute(operation, native_arguments)
            if result.status.value != "completed":
                error = {
                    "service": str(service),
                    "code": result.error.code if result.error else "operation_failed",
                }
                continue
            performed = True
            source_ids.extend(result.source_ids)
            native_results.extend(_native_result_items(str(service), result.data))
        return native_results, performed, error, source_ids


def _contextual_query(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return _normalize_space(value)[:700].rstrip()
    if not isinstance(value, dict):
        raise ValueError("workspace query must be a string or Calendar event context")
    parts: list[str] = []
    title = value.get("title")
    if isinstance(title, str) and title.strip():
        normalized_title = _normalize_space(title)
        parts.append(normalized_title)
        for segment in re.split(r"\s*(?:\||—|–|:)\s*", normalized_title):
            if len(segment.split()) >= 2 and segment not in parts:
                parts.append(segment)
    description = value.get("description")
    if isinstance(description, str) and description.strip():
        compact_description = _compact_description(description)
        if compact_description:
            parts.append(compact_description)
    organizer = value.get("organizer")
    if isinstance(organizer, str) and organizer.strip():
        parts.append(_normalize_space(organizer))
    attendees = value.get("attendees")
    if isinstance(attendees, list):
        useful_attendees = [
            attendee.strip()
            for attendee in attendees
            if isinstance(attendee, str) and attendee.strip()
        ][:3]
        parts.extend(useful_attendees)
    if not parts:
        raise ValueError("Calendar event context contains no searchable fields")
    return _normalize_space(" ".join(parts))[:700].rstrip()


_BOILERPLATE = re.compile(
    r"(?:https?://|www\.|meet\.google\.|zoom\.|teams\.microsoft\.com|"
    r"password|passcode|dial[- ]?in|join (?:the )?meeting|"
    r"confidential|disclaimer|unsubscribe|do not reply|"
    r"kind regards|best regards|sincerely)",
    flags=re.IGNORECASE,
)


def _compact_description(description: str) -> str:
    plain = unescape(re.sub(r"<[^>]+>", " ", description))
    candidates = re.split(r"[\r\n]+|(?<=[.!?])\s+", plain)
    useful: list[str] = []
    for candidate in candidates:
        normalized = _normalize_space(candidate)
        if len(normalized) < 3 or _BOILERPLATE.search(normalized):
            continue
        useful.append(normalized)
        if sum(len(item) for item in useful) >= 350 or len(useful) == 4:
            break
    return " ".join(useful)[:400].rstrip()


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _native_search_text(
    raw_context: object,
    contextual_query: str,
    *,
    prefer_topic: bool = False,
) -> str:
    if isinstance(raw_context, dict):
        title = raw_context.get("title")
        if isinstance(title, str) and title.strip():
            normalized = _normalize_space(title)
            if prefer_topic:
                segments = [
                    segment.strip()
                    for segment in re.split(r"\s*(?:\||—|–|:)\s*", normalized)
                    if segment.strip()
                ]
                if segments:
                    return max(segments, key=lambda segment: len(segment.split()))[:200]
            return normalized[:200]
    return contextual_query[:200]


def _native_result_items(
    service: str, data: StructuredData
) -> list[dict[str, Any]]:
    if service == "gmail":
        values = data.get("emails")
        if not isinstance(values, list):
            return []
        return [
            {
                "service": service,
                "external_resource_id": item.get("id"),
                "title": item.get("subject", ""),
                "snippet": item.get("preview", ""),
                "retrieval_source": "native_fallback",
            }
            for item in values
            if isinstance(item, dict)
        ]
    values = data.get("files")
    if not isinstance(values, list):
        return []
    return [
        {
            "service": service,
            "external_resource_id": item.get("id"),
            "title": item.get("name", ""),
            "source_updated_at": item.get("modifiedTime"),
            "retrieval_source": "native_fallback",
        }
        for item in values
        if isinstance(item, dict)
    ]
