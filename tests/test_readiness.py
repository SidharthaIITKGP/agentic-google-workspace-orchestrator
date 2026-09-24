from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_redis_cache
from app.db.session import get_db_session
from app.main import app


class FakeSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def execute(self, statement: object) -> object:
        if self.error is not None:
            raise self.error
        return object()


class FakeCache:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def ping(self) -> bool:
        if self.error is not None:
            raise self.error
        return True


def request_readiness(
    session: FakeSession,
    cache: FakeCache,
) -> tuple[int, dict[str, object]]:
    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    def override_cache() -> FakeCache:
        return cache

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_redis_cache] = override_cache
    try:
        with TestClient(app) as client:
            response = client.get("/ready")
            return response.status_code, response.json()
    finally:
        app.dependency_overrides.clear()


def test_readiness_succeeds_when_dependencies_are_available() -> None:
    status_code, payload = request_readiness(FakeSession(), FakeCache())

    assert status_code == 200
    assert payload == {
        "status": "ready",
        "services": {"postgresql": "ok", "redis": "ok"},
    }


@pytest.mark.parametrize(
    ("session", "cache", "expected_services"),
    [
        (
            FakeSession(ConnectionError("database unavailable")),
            FakeCache(),
            {"postgresql": "unavailable", "redis": "ok"},
        ),
        (
            FakeSession(),
            FakeCache(ConnectionError("redis unavailable")),
            {"postgresql": "ok", "redis": "unavailable"},
        ),
    ],
)
def test_readiness_identifies_unavailable_dependencies(
    session: FakeSession,
    cache: FakeCache,
    expected_services: dict[str, str],
) -> None:
    status_code, payload = request_readiness(session, cache)

    assert status_code == 503
    assert payload == {"status": "not_ready", "services": expected_services}


def test_liveness_does_not_depend_on_infrastructure() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
