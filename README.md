# Agentic Google Workspace Orchestrator

A Python service that will execute natural-language requests across Gmail, Google Calendar, and Google Drive through project-owned planning and orchestration components.

## Current status

This initial foundation includes a modular FastAPI application, environment-based settings, a process-level health endpoint, and tests. Google APIs, OAuth, LLM calls, persistence, queues, containers, and orchestration logic are not implemented yet.

## Setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Optionally copy `.env.example` to `.env` and adjust the safe development settings.

## Run the application

```bash
python -m uvicorn app.main:app --reload
```

Check the application process:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

This endpoint does not report on unimplemented external services.

## Run tests

```bash
python -m pytest -q
```

## Planned architecture

Requests will flow from an intent classifier to a query planner, a custom DAG executor, specialized Gmail/Calendar/Drive agents, and finally retrieval and response synthesis. Planned supporting services include PostgreSQL with pgvector, Redis, Celery, Google OAuth, and the Google Workspace APIs. See [`docs/architecture.md`](docs/architecture.md) for the boundary between current and planned components.
