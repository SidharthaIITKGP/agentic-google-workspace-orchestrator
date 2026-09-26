from app.schemas.contracts import StepResult, StructuredData


def compact_results_for_synthesis(results: list[StepResult]) -> list[StepResult]:
    return [
        result.model_copy(update={"data": compact_result_data(result.data)})
        for result in results
    ]


def compact_result_data(data: StructuredData) -> StructuredData:
    events = data.get("events")
    if isinstance(events, list):
        return {
            "events": _compact_events(events)
        }

    emails = data.get("emails")
    if isinstance(emails, list):
        return {
            "emails": _select(
                emails,
                ("id", "thread_id", "subject", "sender", "date", "snippet"),
            )
        }

    files = data.get("files")
    if isinstance(files, list):
        compact_files: list[StructuredData] = []
        for file in files[:20]:
            if not isinstance(file, dict):
                continue
            compact_file = {
                key: file[key]
                for key in ("id", "name")
                if key in file
            }
            mime_type = file.get("mime_type", file.get("mimeType"))
            modified_time = file.get("modified_time", file.get("modifiedTime"))
            if mime_type is not None:
                compact_file["mime_type"] = mime_type
            if modified_time is not None:
                compact_file["modified_time"] = modified_time
            compact_files.append(compact_file)
        return {"files": compact_files}

    results = data.get("results")
    if isinstance(results, list):
        compact_results: list[StructuredData] = []
        for result in results[:20]:
            if not isinstance(result, dict):
                continue
            compact_result = {
                key: result[key]
                for key in (
                    "service",
                    "external_resource_id",
                    "title",
                    "score",
                    "source_updated_at",
                    "retrieval_source",
                )
                if key in result
            }
            snippet = result.get("snippet", result.get("chunk_text"))
            if isinstance(snippet, str) and snippet.strip():
                compact_result["snippet"] = snippet.strip()[:300]
            compact_results.append(compact_result)
        compact: StructuredData = {
            "results": compact_results,
            "searched_services": data.get("searched_services", []),
            "index_stale": bool(data.get("index_stale", False)),
            "native_fallback_recommended": bool(
                data.get("native_fallback_recommended", False)
            ),
            "native_fallback_performed": bool(
                data.get("native_fallback_performed", False)
            ),
        }
        timing = data.get("retrieval_timing_ms")
        if isinstance(timing, dict):
            compact["retrieval_timing_ms"] = timing
        freshness = data.get("freshness")
        if isinstance(freshness, dict):
            compact["freshness"] = freshness
        reranking = data.get("reranking")
        if isinstance(reranking, dict):
            compact["reranking"] = reranking
        return compact

    return data


def _select(items: list[object], fields: tuple[str, ...]) -> list[StructuredData]:
    selected: list[StructuredData] = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        selected.append({key: item[key] for key in fields if key in item})
    return selected


def _compact_events(events: list[object]) -> list[StructuredData]:
    compact_events: list[StructuredData] = []
    for event in events[:20]:
        if not isinstance(event, dict):
            continue
        compact_event = {
            key: event[key]
            for key in ("title", "start", "end", "organizer", "status")
            if key in event
        }
        attendees = event.get("attendees")
        if isinstance(attendees, list):
            compact_event["attendees"] = attendees[:5]
            compact_event["attendee_count"] = len(attendees)
        compact_events.append(compact_event)
    return compact_events
