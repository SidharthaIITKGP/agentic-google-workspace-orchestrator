# Contributor Guidance

## Project

This repository implements a natural-language orchestrator for Gmail, Google Calendar, and Google Drive. The stack is Python 3.11+, FastAPI, Pydantic, SQLAlchemy, PostgreSQL with pgvector, Redis, Celery, Groq, Google Workspace APIs, React, TypeScript, Vite, and Docker Compose.

## Conventions

- Keep HTTP routes in `app/api/routes`, configuration in `app/core`, schemas in `app/schemas`, service integrations in `app/agents`, orchestration in `app/orchestration`, and retrieval/sync concerns in their existing modules.
- Use async functions for I/O-bound paths and move blocking Google SDK/model work off the event loop.
- Use complete type hints and Pydantic validation at system boundaries.
- Load configuration from environment variables. Never commit secrets; document variables with placeholders in `.env.example`.
- Preserve user-scoped database access, encrypted credentials, HttpOnly session authentication, deterministic validation, and approval gates for writes.
- Do not add LangChain, LlamaIndex, or another agent framework; reuse the project-owned registry and custom DAG executor.
- Prefer small, focused changes, existing interfaces, and relevant tests. Do not implement unrelated features.
