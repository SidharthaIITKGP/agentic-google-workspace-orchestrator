# Workspace Orchestrator UI

Small React, TypeScript, and Vite demo client for the existing FastAPI application.

## Local development

Copy `.env.example` to `.env`, install dependencies, and start Vite. The default API URL is `http://localhost:8000`. FastAPI must allow `http://localhost:5173` through `FRONTEND_ORIGIN`.

The browser client always sends `credentials: "include"`. OAuth access and refresh tokens remain on the backend and are never stored by this application. Only the current conversation ID is kept in `sessionStorage`.

## Docker

The root Compose file includes an optional `frontend` service on port 5173. It depends only on the healthy API service and does not change the existing API, database, Redis, worker, or Beat topology.

## Tests

The lightweight Vitest suite covers conversation reuse, authentication failures, approval endpoints, clarification rendering, sync status, and suppression of bulky raw action payloads.
