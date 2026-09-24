# Architecture

## Current foundation

The implemented system is a minimal FastAPI service with environment-based settings and a process-level `GET /health` endpoint. The health check confirms only that the HTTP application is responding; it does not claim connectivity to any future dependency.

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

FastAPI will expose the application interface. PostgreSQL with pgvector will support durable and vector data, Redis and Celery will support background execution, and Google OAuth will authorize access to Google Workspace APIs. These integrations, along with LLM calls and orchestration logic, are future work.
