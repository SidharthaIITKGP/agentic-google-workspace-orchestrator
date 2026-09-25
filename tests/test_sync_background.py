import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.contracts import Service
from app.sync.service import WorkspaceSyncService
from app.workers import tasks as task_module
from app.workers.celery_app import celery_app


def test_sync_endpoints_require_authentication() -> None:
    with TestClient(app) as client:
        assert client.post("/api/v1/sync/trigger").status_code == 401
        assert client.get("/api/v1/sync/status").status_code == 401


def test_gmail_sync_is_pagination_aware_and_bounded() -> None:
    async def exercise() -> None:
        list_tokens: list[str | None] = []

        class Request:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        class Messages:
            def list(self, userId, maxResults, pageToken):
                list_tokens.append(pageToken)
                if pageToken is None:
                    return Request({"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "p2"})
                return Request({"messages": [{"id": "m3"}], "nextPageToken": "p3"})

            def get(self, userId, id, format):
                return Request({"id": id, "payload": {"headers": []}, "snippet": id})

        class Users:
            def messages(self):
                return Messages()

        class Gmail:
            def users(self):
                return Users()

        class Clients:
            async def build(self, name, version):
                return Gmail()

        class Indexer:
            def __init__(self):
                self.ids = []

            async def index_item(self, user_id, item):
                self.ids.append(item.external_resource_id)

        indexer = Indexer()
        settings = SimpleNamespace(sync_gmail_max_items=3)
        service = WorkspaceSyncService(None, Clients(), indexer, settings)

        count, cursor = await service._sync_gmail(uuid4())

        assert count == 3
        assert cursor == "p3"
        assert list_tokens == [None, "p2"]
        assert indexer.ids == ["m1", "m2", "m3"]

    asyncio.run(exercise())


def test_one_service_failure_does_not_stop_other_services() -> None:
    async def exercise() -> None:
        service = WorkspaceSyncService(None, None, None, None)
        calls = []

        async def sync_service(user_id, selected):
            calls.append(selected)
            if selected == Service.GMAIL:
                return {"status": "failed", "indexed_items": 0}
            return {"status": "completed", "indexed_items": 1}

        service.sync_service = sync_service
        result = await service.sync_user(uuid4())

        assert result["gmail"]["status"] == "failed"
        assert result["google_calendar"]["status"] == "completed"
        assert result["google_drive"]["status"] == "completed"
        assert calls == [Service.GMAIL, Service.GOOGLE_CALENDAR, Service.GOOGLE_DRIVE]

    asyncio.run(exercise())


def test_sync_state_records_success_and_safe_failure() -> None:
    async def exercise() -> None:
        state = SimpleNamespace(
            status="pending",
            last_attempted_sync=None,
            last_successful_sync=None,
            sync_cursor=None,
            error_details=None,
        )

        class Session:
            def __init__(self):
                self.commits = 0

            async def commit(self):
                self.commits += 1

            async def rollback(self):
                return None

        session = Session()
        service = WorkspaceSyncService(session, None, None, None)

        async def state_for(user_id, selected):
            return state

        async def successful(user_id, since=None):
            return 2, "cursor"

        service._state = state_for
        service._sync_gmail = successful
        result = await service.sync_service(uuid4(), Service.GMAIL)

        assert result == {"status": "completed", "indexed_items": 2}
        assert state.status == "completed"
        assert state.last_attempted_sync is not None
        assert state.last_successful_sync is not None
        assert state.sync_cursor == "cursor"
        assert state.error_details is None

        async def failing(user_id, since=None):
            raise RuntimeError("sensitive provider detail")

        service._sync_gmail = failing
        result = await service.sync_service(uuid4(), Service.GMAIL)

        assert result["status"] == "failed"
        assert state.status == "failed"
        assert state.error_details == {"type": "RuntimeError"}
        assert "sensitive" not in str(state.error_details)

    asyncio.run(exercise())


def test_celery_task_delegates_to_async_sync(monkeypatch) -> None:
    user_id = uuid4()

    async def fake_sync(selected_user_id):
        assert selected_user_id == user_id
        return {"status": "completed"}

    monkeypatch.setattr(task_module, "_sync_user", fake_sync)

    assert task_module.sync_user_task.run(str(user_id)) == {"status": "completed"}


def test_duplicate_sync_lock_skips_work(monkeypatch) -> None:
    class RedisClient:
        async def set(self, *args, **kwargs):
            return False

        async def aclose(self):
            return None

    monkeypatch.setattr(
        task_module.Redis,
        "from_url",
        lambda *args, **kwargs: RedisClient(),
    )

    result = asyncio.run(task_module._sync_user(uuid4()))

    assert result == {"status": "skipped", "reason": "sync_already_running"}


def test_periodic_connected_user_task_is_registered_every_fifteen_minutes() -> None:
    schedule = celery_app.conf.beat_schedule[
        "enqueue-connected-users-every-15-minutes"
    ]

    assert schedule["task"] == "workspace.enqueue_connected_users"
    assert schedule["schedule"] == 900.0
    assert schedule["options"]["expires"] < schedule["schedule"]


def test_periodic_task_enqueues_each_connected_user(monkeypatch) -> None:
    async def exercise() -> None:
        user_ids = [uuid4(), uuid4()]

        class Values:
            def all(self):
                return user_ids

        class Session:
            async def scalars(self, statement):
                return Values()

        class Context:
            async def __aenter__(self):
                return Session()

            async def __aexit__(self, *args):
                return None

        queued = []
        monkeypatch.setattr(task_module, "async_session_factory", Context)
        monkeypatch.setattr(
            task_module.sync_user_task,
            "apply_async",
            lambda **kwargs: queued.append(kwargs),
        )

        result = await task_module._enqueue_connected_users()

        assert result == {"queued_users": 2}
        assert [entry["args"][0] for entry in queued] == [
            str(user_id) for user_id in user_ids
        ]
        assert all(entry["expires"] > 0 for entry in queued)

    asyncio.run(exercise())


def test_sync_lock_release_is_owner_safe() -> None:
    async def exercise() -> None:
        calls = []

        class RedisClient:
            async def eval(self, *args):
                calls.append(args)
                return 1

        released = await task_module._release_sync_lock(
            RedisClient(), "sync-lock:user", "owner-token"
        )

        assert released is True
        assert calls[0][-2:] == ("sync-lock:user", "owner-token")
        assert "redis.call('get'" in calls[0][0]

    asyncio.run(exercise())


def test_incremental_gmail_sync_uses_previous_success_timestamp() -> None:
    async def exercise() -> None:
        captured = {}

        class Request:
            def execute(self):
                return {"messages": []}

        class Messages:
            def list(self, **kwargs):
                captured.update(kwargs)
                return Request()

        class Users:
            def messages(self):
                return Messages()

        class Gmail:
            def users(self):
                return Users()

        class Clients:
            async def build(self, name, version):
                return Gmail()

        service = WorkspaceSyncService(
            None,
            Clients(),
            None,
            SimpleNamespace(sync_gmail_max_items=10),
        )
        since = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

        count, _ = await service._sync_gmail(uuid4(), since=since)

        assert count == 0
        assert captured["q"] == f"after:{int(since.timestamp())}"

    asyncio.run(exercise())
