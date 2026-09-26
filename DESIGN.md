# System Design

## A. Problem statement

Google Workspace information is split across email, calendars, and files. This system accepts one natural-language request, determines which services are required, constructs a validated workflow, retrieves or changes the relevant resources, and returns a grounded response. It supports both independent multi-service reads and dependent workflows in which one result supplies context to later steps.

## B. Goals

- Natural-language access to Gmail, Google Calendar, and Google Drive.
- Multi-service workflows with explicit dependencies and concurrent independent work.
- Grounded native and semantic retrieval with bounded result sets.
- Explicit human approval before consequential external writes.
- Persistent conversation and execution records with visible partial failures.
- User-scoped credentials, data, cache entries, retrieval, and approvals.
- Periodic, bounded background synchronization into a local semantic index.

## C. Non-goals

- Replacing Google APIs as the source of truth.
- Autonomous destructive or consequential writes.
- Arbitrary web/browser automation.
- A managed vector database or hosted embedding dependency.
- LangChain, LlamaIndex, or another general agent framework.
- Claiming that the current local deployment supports internet scale.

## D. Architecture

The FastAPI query route loads recent conversation context and invokes a Groq-backed classifier. The classifier returns a validated `Intent`, including services, extracted entities, and clarification state. A query planner uses the agent registry's planner-visible operation specifications to create an `ExecutionPlan`.

The operation registry is the boundary between plans and implementations. It advertises supported operations and argument contracts, validates operation names and arguments, and dispatches typed structured data to Gmail, Calendar, Drive, or workspace-search agents. Pydantic validates the plan graph before execution.

The custom DAG executor persists an execution and its steps, schedules dependency-ready nodes, resolves references to prior results, applies write-approval policy, and stores structured results/errors. Native agents call Google APIs; `HybridWorkspaceSearch` queries the local index. Compact results are sent to the Groq synthesizer, with a deterministic grounded fallback if synthesis fails.

See [docs/architecture.md](docs/architecture.md) for the component diagram.

## E. Why custom orchestration

The domain has a small, auditable operation set and strict security boundaries. A project-owned registry and DAG executor make supported operations, argument validation, dependency rules, approval gates, persistence, and failure semantics explicit. This avoids hidden framework behavior and keeps Google API calls, user isolation, and side effects directly testable.

## F. DAG planning and execution

An execution plan contains uniquely identified nodes with a service, extensible operation name, structured arguments, and dependency IDs. Graph validation rejects duplicate IDs, references to nonexistent nodes, self-dependencies, cycles, and malformed reference objects.

Independent dependency-ready nodes execute concurrently. Sequential nodes wait for their dependencies. Arguments may contain a serializable prior-output reference:

```json
{"$step":"calendar_step","path":["events",0,"title"]}
```

The executor resolves the path only against the declared, completed dependency. List indices are supported. A missing element or field produces an explicit reference-resolution failure; unrelated data is never substituted. A failed dependency causes dependent nodes to be skipped with a recorded reason, while independent branches may still complete.

## G. Retrieval architecture

Synchronization normalizes Google resources into `workspace_items`. Deterministically generated `document_chunks` hold searchable text and 384-dimensional vectors from `sentence-transformers/all-MiniLM-L6-v2`. The vector column has an HNSW cosine index.

At query time, retrieval:

1. normalizes and embeds the semantic query;
2. reuses a user/model/query-scoped process or Redis embedding cache when available;
3. filters SQL by `user_id`, requested services, deletion state, and optional metadata;
4. combines 75% cosine similarity with 25% PostgreSQL text relevance;
5. retrieves a bounded candidate pool;
6. applies explainable relevance filtering, service-aware selection, Gmail-thread deduplication where metadata permits, and `top_k` bounds.

Instrumentation separates embedding, database, and total retrieval time and records cache hits. Per-service sync status determines index freshness. A fresh useful index serves hybrid results. A stale index is reported honestly; stale empty retrieval may invoke a native read fallback. `native_fallback_performed` is true only when that Google API call actually ran.

## H. Synchronization

Celery Beat registers `workspace.enqueue_connected_users` every 900 seconds with an expiry shorter than the interval. It enumerates distinct users with stored Google credentials and enqueues `workspace.sync_user` jobs.

Each user job acquires a Redis `SET NX EX` lock and renews it periodically. Release uses a compare-and-delete script, preventing one worker from deleting another worker's lock. Gmail and Drive item counts and the Calendar lookback/lookahead window are configurable. Each service is attempted separately; successful commits update `last_successful_sync`, while failures roll back, record a safe exception type, and allow the next service to proceed.

Credentials are decrypted only in the backend worker when constructing authorized Google clients.

## I. Write safety

Write-capable operations are recognized by deterministic registry policy. Instead of calling Google immediately, the executor persists the fully resolved `{service, operation, arguments}` proposal and returns an approval ID. The UI displays a sanitized preview.

Approve and reject endpoints require the owning HttpOnly session and lock the approval row. Approval executes exactly the stored action without replanning. Rejection records a skipped step. A non-pending approval returns HTTP 409, preventing duplicate execution. Calendar event creation, including optional Google Meet creation and attendee notifications, remains behind this gate.

## J. Security

- OAuth state and PKCE verifier data are short-lived in Redis.
- Google access and refresh tokens are Fernet-encrypted at rest.
- Browser authentication uses an HttpOnly, SameSite=Lax session cookie; production mode sets `Secure`.
- Tokens and API keys are never returned to frontend JavaScript or stored in localStorage.
- Database reads and writes use authenticated `user_id` ownership constraints.
- CORS allows the configured frontend origin, credentials, and only required methods/headers.
- The UI renders backend content as text, not trusted HTML, and external links use safe browser attributes.
- Deterministic operation validation and approval gates remain authoritative; LLM output cannot directly cause a write.
- Secrets are supplied through environment variables and excluded from Git.

## K. Failure handling

The API distinguishes liveness from readiness. Provider interpretation failures return a safe 502 without stack traces. Invalid generated operations fail before Google calls. Execution results retain completed, failed, skipped, and awaiting-approval states, allowing partial success to be synthesized accurately. Failed/skipped searches are not reported as successful empty searches.

Clarification stops planning when required details cannot be inferred safely, especially for ambiguous writes. Read-only contextual retrieval can use semantic defaults. Dependency failures skip downstream nodes. Sync errors are isolated by service. Stale-index metadata and native-fallback metadata communicate what was recommended and what actually happened.

## L. Scalability path

The current Docker Compose deployment is development/demo oriented; it does not claim one-million-user capacity. A credible scale-out design would include:

- stateless horizontal FastAPI workers behind a load balancer;
- managed Redis with separate cache, session, broker, and coordination capacity;
- independently scalable Celery pools and queues partitioned by service/tenant;
- jittered per-user sync scheduling, quota-aware batching, backpressure, and dead-letter handling;
- PostgreSQL connection pooling, read replicas, time/user partitioning, and eventual tenant sharding;
- pgvector indexes partitioned by tenant/service or a dedicated retrieval tier as corpus size grows;
- cache admission/eviction policies and reusable embedding workers;
- per-user and per-project Google quota budgets, retry-after handling, and rate limiting;
- idempotency keys and stronger distributed workflow coordination;
- multi-region APIs with region-pinned user data, queues, and credentials where compliance requires it.

These changes require load tests, failure testing, quota modeling, and operational monitoring before making capacity claims.

## M. Tradeoffs

- **Local embeddings:** avoid a hosted embedding API and keep indexed text local, but CPU cold starts and inference latency can be significant.
- **Native versus indexed search:** native APIs are fresh and authoritative but weaker for cross-service semantic context; the local index improves relevance at the cost of eventual consistency.
- **Fifteen-minute freshness target:** reduces Google API load but permits a bounded stale window and depends on worker/Beat health.
- **Approval latency:** adds a user interaction but prevents accidental external side effects and enables an audit trail.
- **PDF handling:** metadata-only indexing is simple and predictable, but cannot answer questions about PDF body text without future extraction/OCR.
- **Default timezone:** deterministic and configurable, but currently one configured default rather than a persisted per-user preference.

## N. Future improvements

- Persist per-user locale/timezone preferences.
- Add robust PDF text extraction and optional OCR.
- Add production observability, rate limits, structured tracing, and queue dashboards.
- Expand the retrieval evaluation fixture set and record reproducible measured baselines.
- Add provider-independent LLM evaluation and stricter plan-quality scoring.
- Add production deployment manifests, managed-secret integration, and restore testing.
