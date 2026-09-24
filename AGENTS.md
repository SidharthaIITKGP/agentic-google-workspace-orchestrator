# Contributor Guidance

## Project

Build a natural-language orchestrator for Gmail, Google Calendar, and Google Drive. The planned stack is Python 3.11+, FastAPI, Pydantic, PostgreSQL with pgvector, Redis, Celery, an OpenAI or Anthropic model, Google Workspace APIs, and Docker Compose.

## Conventions

- Keep HTTP routes in `app/api/routes`, shared configuration in `app/core`, and Pydantic models in `app/schemas`. Add domain modules only when their functionality is implemented.
- Use async functions for I/O-bound application paths. Do not perform blocking I/O in the event loop.
- Use complete type hints and Pydantic validation at system boundaries.
- Load configuration from environment variables with safe defaults where appropriate. Never commit secrets; document variables in `.env.example`.
- Do not add LangChain, LlamaIndex, or other agent frameworks. Orchestration will use project-owned interfaces and a custom DAG executor.
- Prefer small, focused changes. Reuse existing modules and interfaces and avoid duplicate abstractions.
- Run relevant tests after changes.
- Do not implement unrelated future features.
