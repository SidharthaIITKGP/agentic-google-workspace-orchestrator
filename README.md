# Agentic Google Workspace Orchestrator

A Python service that will execute natural-language requests across Gmail, Google Calendar, and Google Drive through project-owned planning and orchestration components.

## Current status

The core application now includes Google OAuth, encrypted credential storage and refresh, Gmail/Calendar/Drive agents, structured Groq classification and planning through its OpenAI-compatible API, concurrent DAG execution, approval-gated writes, conversation context, PostgreSQL persistence, Redis, and health/readiness checks. Background synchronization, retrieval ingestion, and Celery remain future work.

## Google OAuth and query API

Configure these values in `.env` using credentials from Google Cloud and an application-generated Fernet key:

```dotenv
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
TOKEN_ENCRYPTION_KEY=...
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
```

Start authentication in a browser at `http://localhost:8000/api/v1/auth/google`. The callback stores only encrypted access and refresh tokens, then creates an HttpOnly application session cookie.

After authentication, open `http://localhost:8000/docs` in the same browser and use `POST /api/v1/query`; the HttpOnly session cookie is sent automatically. For an API client, retain the callback cookie and submit:

```bash
curl -b "workspace_session=<session-cookie>" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is on my calendar tomorrow?"}' \
  http://localhost:8000/api/v1/query
```

Consequential operations return a pending approval rather than executing immediately. Approve or reject the returned identifier with `POST /api/v1/actions/{approval_id}/approve` or `POST /api/v1/actions/{approval_id}/reject`, using the same session cookie.

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

Readiness performs bounded live checks against PostgreSQL and Redis:

```bash
curl http://127.0.0.1:8000/ready
```

`GET /health` is a lightweight liveness probe and remains available even when infrastructure is unavailable. `GET /ready` returns HTTP 200 only when both dependencies respond; otherwise it returns HTTP 503 and marks each dependency as `ok` or `unavailable` without exposing internal errors.

## Docker Compose development environment

Prepare the local environment file before starting the containers:

```bash
cp .env.example .env
```

The checked-in values are development-only placeholders. Change them for any shared or non-local environment. Inside Compose, the API reaches PostgreSQL at `db` and Redis at `redis`; local defaults use `localhost`. `DATABASE_URL` must use the `postgresql+psycopg` driver. `REDIS_KEY_NAMESPACE` isolates cache keys, while pool sizes and dependency timeouts can be adjusted through the variables documented in `.env.example`.

Importing and starting the application does not eagerly connect to either service. Database sessions connect when used, and the lifecycle-managed Redis pool connects on its first command.

Build and start the API, PostgreSQL with pgvector, and Redis:

```bash
docker compose up --build -d
```

Inspect container health and follow logs:

```bash
docker compose ps
docker compose logs -f api
```

The API health endpoint is available at `http://127.0.0.1:8000/health`. It reports only that the FastAPI process is responding; it does not verify PostgreSQL or Redis connectivity.

For routine shutdown, preserve the PostgreSQL data volume:

```bash
docker compose down
```

PostgreSQL data is stored in the named `postgres_data` volume and survives routine container shutdown and recreation. Running `docker compose down -v` deletes that persistent database data and should not be used for routine shutdown.

## Database migrations

Database schema changes are versioned with Alembic and use the same `DATABASE_URL` as the application. Migrations are explicit operational commands; FastAPI startup does not run them automatically and the application does not use `Base.metadata.create_all()`.

With the Compose services running, inspect and apply migrations from the API container:

```bash
docker compose exec api python -m alembic current
docker compose exec api python -m alembic upgrade head
docker compose exec api python -m alembic check
```

Create future migration revisions only after intentionally changing SQLAlchemy metadata:

```bash
docker compose exec api python -m alembic revision --autogenerate -m "describe schema change"
```

## Run tests

```bash
python -m pytest -q
```

The standard suite uses dependency overrides and in-memory fakes; it does not require live infrastructure. To verify actual connectivity through the running API container:

```bash
docker compose exec api python -m app.db.check_connectivity
curl http://127.0.0.1:8000/ready
```

Expected connectivity output is `postgresql: ok` and `redis: ok`; readiness should return HTTP 200 with both services marked `ok`.

## Planned architecture

Requests will flow from an intent classifier to a query planner, a custom DAG executor, specialized Gmail/Calendar/Drive agents, and finally retrieval and response synthesis. Planned supporting services include PostgreSQL with pgvector, Redis, Celery, Google OAuth, and the Google Workspace APIs. See [`docs/architecture.md`](docs/architecture.md) for the boundary between current and planned components.
