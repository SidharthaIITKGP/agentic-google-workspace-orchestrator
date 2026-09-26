# API Reference

Base URL for local development: `http://localhost:8000`

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
- Browser-authenticated endpoints use the HttpOnly `workspace_session` cookie. Google access and refresh tokens are never API inputs or frontend-visible values.

Examples below abbreviate variable UUIDs and service result payloads. FastAPI/Pydantic returns HTTP 422 for malformed request bodies or path/query parameters.

## Liveness

### `GET /health`

Authentication: none.

Returns only FastAPI process liveness.

```json
{"status":"ok"}
```

Status: `200`.

## Readiness

### `GET /ready`

Authentication: none.

Performs bounded `SELECT 1` and Redis `PING` checks.

Successful response (`200`):

```json
{"status":"ready","services":{"postgresql":"ok","redis":"ok"}}
```

Unavailable dependency (`503`):

```json
{"status":"not_ready","services":{"postgresql":"ok","redis":"unavailable"}}
```

## Google authentication

### `GET /api/v1/auth/google`

Authentication: none. Redirects to Google's OAuth consent flow and stores short-lived OAuth state/PKCE data in Redis.

```bash
open http://localhost:8000/api/v1/auth/google
```

Statuses: `307` redirect; `503` when OAuth is not configured; `500` if the flow cannot be initialized.

### `GET /api/v1/auth/google/callback?code=...&state=...`

Authentication: Google callback parameters. This endpoint is normally invoked by Google, not manually.

It verifies one-time state, exchanges the code, encrypts credentials, creates/updates the user, stores a Redis application session, and sets the HttpOnly `workspace_session` cookie.

Response (`200`):

```json
{"status":"authenticated","user_id":"11111111-1111-1111-1111-111111111111"}
```

Common statuses: `400` invalid/expired state; `502` Google exchange/profile/incomplete credential failure; `503` OAuth or credential encryption not configured.

## Natural-language query

### `POST /api/v1/query`

Authentication: required session cookie.

Request:

```json
{
  "query": "What is on my calendar tomorrow?",
  "conversation_id": null
}
```

`query` is required (1–10,000 characters). `conversation_id` is optional; reuse the returned ID for follow-up context.

Response (`200`):

```json
{
  "response": "You have one event tomorrow...",
  "conversation_id": "22222222-2222-2222-2222-222222222222",
  "execution_id": "33333333-3333-3333-3333-333333333333",
  "intent": {
    "intent_name": "calendar_search",
    "required_services": ["google_calendar"],
    "extracted_entities": {},
    "requires_clarification": false,
    "clarification_question": null
  },
  "actions_taken": [
    {"step_id":"step1","data":{"events":[]}}
  ],
  "pending_approvals": [],
  "errors": []
}
```

For a write, `pending_approvals` includes `step_id`, `approval_id`, and, when available, a sanitized `proposed_action` containing safe fields such as service, operation, title, start/end, attendees, or target IDs. The full stored proposal is not exposed.

Clarification responses have `execution_id: null` and return the clarification question in `response`; the same `conversation_id` must be used for the answer.

Common statuses: `400` invalid generated request; `401` missing/expired session; `404` conversation not found or not owned by user; `422` invalid body; `502` LLM interpretation failure.

Example:

```bash
curl -b cookies.txt -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"query":"Show my latest unread emails","conversation_id":null}' \
  http://localhost:8000/api/v1/query
```

## Action approval

Writes returned by the query endpoint remain pending until one of these endpoints is called. Both routes lock and verify the user-owned approval record. Already processed approvals return a conflict and are not executed twice.

### `POST /api/v1/actions/{approval_id}/approve`

Authentication: required session cookie. Body: none.

Response (`200`):

```json
{
  "approval_id":"44444444-4444-4444-4444-444444444444",
  "status":"approved",
  "result":{"event":{"id":"provider-resource-id","meet_url":"https://meet.google.com/..."}}
}
```

The result shape depends on the approved operation. Common statuses: `401`, `404` approval not found for user, `409` no longer pending/invalid stored action/missing step, `502` Google execution failure.

```bash
curl -X POST -b cookies.txt \
  http://localhost:8000/api/v1/actions/44444444-4444-4444-4444-444444444444/approve
```

### `POST /api/v1/actions/{approval_id}/reject`

Authentication: required session cookie. Body: none.

Response (`200`):

```json
{
  "approval_id":"44444444-4444-4444-4444-444444444444",
  "status":"rejected",
  "result":null
}
```

Common statuses: `401`, `404`, `409` already processed.

## Workspace synchronization

### `POST /api/v1/sync/trigger`

Authentication: required session cookie. Body: none. Enqueues work and returns immediately (`202`).

```json
{"status":"queued","task_id":"celery-task-id"}
```

```bash
curl -X POST -b cookies.txt http://localhost:8000/api/v1/sync/trigger
```

Common statuses: `202`; `401` unauthenticated.

### `GET /api/v1/sync/status`

Authentication: required session cookie.

Response (`200`):

```json
{
  "services":[
    {
      "service":"gmail",
      "status":"completed",
      "last_attempted_sync":"2026-09-26T08:00:00+00:00",
      "last_successful_sync":"2026-09-26T08:00:10+00:00",
      "error":null
    },
    {
      "service":"google_calendar",
      "status":"pending",
      "last_attempted_sync":null,
      "last_successful_sync":null,
      "error":null
    },
    {
      "service":"google_drive",
      "status":"failed",
      "last_attempted_sync":"2026-09-26T08:00:00+00:00",
      "last_successful_sync":null,
      "error":{"type":"ExampleError"}
    }
  ]
}
```

Common statuses: `200`; `401` unauthenticated.

## Exporting OpenAPI

With the API running, export the generated schema without hand-maintaining it:

```bash
curl --fail http://localhost:8000/openapi.json -o docs/openapi.json
```

The checked-in Postman collection at [docs/Agentic_Workspace_Orchestrator.postman_collection.json](docs/Agentic_Workspace_Orchestrator.postman_collection.json) contains the same public routes without credentials.
