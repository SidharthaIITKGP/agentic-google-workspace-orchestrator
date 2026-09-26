# Five-Minute Demo Script

## 0:00–0:30 — Problem and architecture

- Introduce the project as a natural-language orchestrator across Gmail, Calendar, and Drive.
- Show the architecture diagram briefly: Groq classification/planning, validated custom DAG, specialized agents, local pgvector retrieval, and explicit approval for writes.
- State that Google remains authoritative and the index supplements semantic search.

## 0:30–1:15 — UI and synchronization

- Open `http://localhost:5173` with an authenticated demo session.
- Point out Gmail, Calendar, and Drive sync status and last-successful timestamps.
- If needed, click **Sync now** once. Explain that it queues Celery work and does not block the UI.

## 1:15–2:00 — Multi-service read

Submit:

> Show my 3 latest emails, tomorrow's calendar events, and 3 recently modified Drive files.

- Show service badges and the concise grounded response.
- Expand execution details to demonstrate independent steps and their statuses.
- Avoid expanding large raw payloads.

## 2:00–3:00 — Contextual orchestration

Submit:

> Prepare me for my next meeting and find related emails and files.

- Show Calendar discovery first.
- Show dependent Gmail and Drive workspace retrieval using discovered meeting context.
- Explain that those two branches can run concurrently after Calendar completes.
- Point out index freshness/fallback status without claiming a fallback ran unless the response says it did.

## 3:00–4:15 — Controlled write

Submit with a real test-only attendee instead of the placeholder:

> Schedule a Google Meet with demo@example.com tomorrow at 10 AM.

- Show that no event is created immediately.
- Review the approval card: title, attendee, timezone-aware start/end, and Google Meet flag.
- Click **Approve** deliberately.
- Show the resulting Calendar event and real Meet URL. Mention duplicate approval protection.

## 4:15–4:45 — Persistence and background work

- Briefly show `docs/architecture.md` and `docs/ER_DIAGRAM.md`.
- Mention PostgreSQL/pgvector, local MiniLM embeddings, Redis, Celery worker, and 15-minute Beat scheduling.
- Mention user-scoped retrieval and encrypted Google credentials.

## 4:45–5:00 — Close

- Summarize: multi-service reads, dependent DAG orchestration, grounded semantic retrieval, persisted context, and approval-gated writes.
- State limitations plainly: eventual index consistency, local CPU embedding latency, and metadata-only PDF indexing.

## Do not show

- `.env`, API keys, encryption keys, client secrets, session cookies, or OAuth tokens.
- Private email bodies or attendee lists that are unnecessary for the demonstration.
- Raw database credential rows, giant execution payloads, pagination tokens, or stack traces.
- Approval of an action whose recipient/time has not been checked.
