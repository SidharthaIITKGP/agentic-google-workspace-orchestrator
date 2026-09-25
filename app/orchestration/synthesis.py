from typing import Any

from app.llm.prompts import SYNTHESIS_SYSTEM_PROMPT
from app.llm.provider import LLMProvider, LLMProviderError
from app.schemas.contracts import ExecutionStatus, StepResult


class ResponseSynthesizer:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def synthesize(self, query: str, results: list[StepResult]) -> str:
        if _has_contextual_workspace_results(results):
            return grounded_response(results)
        output = await self._provider.generate_json(
            SYNTHESIS_SYSTEM_PROMPT,
            {
                "query": query,
                "execution_results": [
                    result.model_dump(mode="json") for result in results
                ],
                "execution_facts": _execution_facts(results),
            },
        )
        response = output.get("response")
        if not isinstance(response, str) or not response.strip():
            raise LLMProviderError("Response synthesizer returned invalid output")
        response = response.strip()
        if any(
            result.status in {ExecutionStatus.FAILED, ExecutionStatus.SKIPPED}
            for result in results
        ) or _looks_generic_response(response):
            return grounded_response(results)
        return response


def _execution_facts(results: list[StepResult]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for result in results:
        collection_name, collection = _primary_collection(result.data)
        facts.append(
            {
                "step_id": result.step_id,
                "status": result.status.value,
                "attempted": result.status != ExecutionStatus.SKIPPED,
                "collection": collection_name,
                "match_count": len(collection) if collection is not None else None,
                "completed_empty": (
                    result.status == ExecutionStatus.COMPLETED
                    and collection is not None
                    and not collection
                ),
                "error_code": result.error.code if result.error else None,
                "searched_services": result.data.get("searched_services", []),
                "index_stale": bool(result.data.get("index_stale", False)),
                "native_fallback_recommended": bool(
                    result.data.get("native_fallback_recommended", False)
                ),
                "native_fallback_performed": bool(
                    result.data.get("native_fallback_performed", False)
                ),
            }
        )
    return facts


def _primary_collection(data: dict[str, Any]) -> tuple[str | None, list[Any] | None]:
    for key in ("events", "emails", "files", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return key, value
    return None, None


def grounded_response(results: list[StepResult]) -> str:
    statements: list[str] = []
    for result in results:
        if result.status != ExecutionStatus.COMPLETED:
            continue
        collection_name, collection = _primary_collection(result.data)
        if collection is None:
            continue
        label = {
            "events": "Calendar search",
            "emails": "Email search",
            "files": "Drive search",
            "results": "Workspace search",
        }[collection_name]
        if collection_name == "results":
            label = _workspace_search_label(result.data)
        if not collection:
            if collection_name == "results":
                statement = f"{label} completed with no sufficiently relevant matches."
                statement += _retrieval_status_suffix(result.data)
            else:
                statement = f"{label} completed with no matching results."
            statements.append(statement)
            continue
        if collection_name == "events" and isinstance(collection[0], dict):
            event = collection[0]
            title = event.get("title")
            start = event.get("start")
            attendees = event.get("attendees")
            statement = f"The next calendar event is {title}" if title else "A calendar event was found"
            if start:
                statement += f" at {start}"
            statement += "."
            if isinstance(attendees, list) and attendees:
                shown = [str(item) for item in attendees if item][:5]
                statement += " Attendees: " + ", ".join(shown)
                attendee_count = event.get("attendee_count", len(attendees))
                if isinstance(attendee_count, int) and attendee_count > len(shown):
                    statement += f", and {attendee_count - len(shown)} more"
                statement += "."
            statements.append(statement)
        elif collection_name == "files":
            names = [
                str(item.get("name") or item.get("title"))
                for item in collection[:5]
                if isinstance(item, dict) and (item.get("name") or item.get("title"))
            ]
            statement = f"Drive search completed with {len(collection)} matching result(s)."
            if names:
                statement += " In returned order: " + ", ".join(names) + "."
            statements.append(statement)
        elif collection_name == "results":
            findings = [
                _compact_finding(item)
                for item in collection[:5]
                if isinstance(item, dict) and item.get("title")
            ]
            result_kind = (
                "native fallback result(s)"
                if result.data.get("native_fallback_performed")
                else "relevant result(s)"
            )
            statement = f"{label} completed with {len(collection)} {result_kind}."
            if findings:
                statement += " Matches: " + "; ".join(findings) + "."
            statement += _retrieval_status_suffix(result.data)
            statements.append(statement)
        else:
            statements.append(
                f"{label} completed with {len(collection)} matching result(s)."
            )

    failed = [result.step_id for result in results if result.status == ExecutionStatus.FAILED]
    skipped = [result.step_id for result in results if result.status == ExecutionStatus.SKIPPED]
    pending = [
        result
        for result in results
        if result.status == ExecutionStatus.AWAITING_APPROVAL
    ]
    for result in pending:
        approval_id = result.data.get("approval_id")
        statement = f"Step {result.step_id} is awaiting approval"
        if approval_id:
            statement += f" (approval ID: {approval_id})"
        statements.append(statement + ".")
    if failed:
        statements.append(
            "The following searches failed, so their results could not be checked: "
            + ", ".join(failed)
            + "."
        )
    if skipped:
        statements.append(
            "The following searches were not attempted because a dependency was unavailable: "
            + ", ".join(skipped)
            + "."
        )
    return " ".join(statements) or "The requested searches could not be completed."


def _workspace_search_label(data: dict[str, Any]) -> str:
    services = data.get("searched_services")
    if services == ["gmail"]:
        return "Indexed Gmail search"
    if services == ["google_drive"]:
        return "Indexed Drive search"
    return "Indexed workspace search"


def _compact_finding(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled")
    snippet = item.get("snippet")
    if isinstance(snippet, str) and snippet.strip():
        return f"{title} — {snippet.strip()[:160]}"
    return title


def _has_contextual_workspace_results(results: list[StepResult]) -> bool:
    has_calendar = any(
        isinstance(result.data.get("events"), list)
        for result in results
    )
    has_workspace = any(
        isinstance(result.data.get("results"), list)
        and bool(result.data.get("searched_services"))
        for result in results
    )
    return has_calendar and has_workspace


def _retrieval_status_suffix(data: dict[str, Any]) -> str:
    stale = bool(data.get("index_stale", False))
    fallback = bool(data.get("native_fallback_performed", False))
    if stale and fallback:
        return " The semantic index was stale, so native read-only fallback was used."
    if stale:
        return " The semantic index was stale; native fallback was not performed."
    if fallback:
        return " Native read-only fallback was used."
    return ""


def _looks_generic_response(response: str) -> bool:
    normalized = response.casefold()
    return all(
        phrase in normalized
        for phrase in ("completed", "step", "available service results")
    )


_deterministic_partial_response = grounded_response
