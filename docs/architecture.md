# Architecture

## Current foundation

The implemented system is a minimal FastAPI service with environment-based settings and a process-level `GET /health` endpoint. The health check confirms only that the HTTP application is responding; it does not claim connectivity to any future dependency.

Phase 0.2 adds shared, JSON-serializable Pydantic contracts for classified intents, execution plans and steps, step results, and service-agent results. A common async `ServiceAgent` protocol defines the boundary future Gmail, Calendar, and Drive implementations will follow; no service implementation or execution engine exists yet.

## Shared data flow

An intent carries the requested services and extracted entities into planning. An execution plan contains independent or dependent steps, and each completed step produces a structured step result. Future service agents accept structured input and return structured agent results with source identifiers.

Step arguments may refer to prior output with `{"$step": "step_id", "path": ["field", 0]}`. The referenced step must be an explicit dependency. Contracts validate the plan graph and reference shape, but reference resolution is planned work.

## Planned application flow

The following components are planned and are not yet implemented:

```text
User Query
  -> Intent Classifier
  -> Query Planner
  -> Custom DAG Executor
  -> Gmail / Calendar / Drive Agents
  -> Retrieval and Response Synthesizer
```

FastAPI exposes the current application interface. PostgreSQL with pgvector will support durable and vector data, Redis and Celery will support background execution, and Google OAuth will authorize access to Google Workspace APIs. These integrations, along with LLM calls, planning, DAG execution, and orchestration logic, are future work.
