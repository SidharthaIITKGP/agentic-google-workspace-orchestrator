import asyncio
from collections.abc import AsyncIterator
from types import TracebackType

import pytest

import app.db.session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.rollback_called = False

    async def rollback(self) -> None:
        self.rollback_called = True


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.exited = False

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True


def test_database_dependency_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[FakeSession, FakeSessionContext]:
        session = FakeSession()
        context = FakeSessionContext(session)
        monkeypatch.setattr(session_module, "async_session_factory", lambda: context)

        dependency: AsyncIterator[FakeSession] = session_module.get_db_session()  # type: ignore[assignment]
        assert await anext(dependency) is session
        await dependency.aclose()
        return session, context

    session, context = asyncio.run(exercise())

    assert context.exited is True
    assert session.rollback_called is False


def test_database_dependency_rolls_back_failed_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> tuple[FakeSession, FakeSessionContext]:
        session = FakeSession()
        context = FakeSessionContext(session)
        monkeypatch.setattr(session_module, "async_session_factory", lambda: context)

        dependency: AsyncIterator[FakeSession] = session_module.get_db_session()  # type: ignore[assignment]
        assert await anext(dependency) is session
        with pytest.raises(RuntimeError, match="transaction failed"):
            await dependency.athrow(RuntimeError("transaction failed"))
        return session, context

    session, context = asyncio.run(exercise())

    assert session.rollback_called is True
    assert context.exited is True
