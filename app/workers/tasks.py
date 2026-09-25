import asyncio
from contextlib import suppress
import logging
import secrets
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select

from app.auth.security import TokenCipher
from app.core.config import get_settings
from app.db.models import GoogleCredential
from app.db.session import async_session_factory
from app.integrations.google import GoogleClientFactory
from app.retrieval.embeddings import embedding_provider_from_settings
from app.retrieval.indexer import WorkspaceIndexer
from app.sync.service import WorkspaceSyncService
from app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


@celery_app.task(name="workspace.sync_user")
def sync_user_task(user_id: str) -> dict:
    return asyncio.run(_sync_user(UUID(user_id)))


@celery_app.task(name="workspace.enqueue_connected_users")
def enqueue_connected_users_task() -> dict[str, int]:
    return asyncio.run(_enqueue_connected_users())


async def _sync_user(user_id: UUID) -> dict:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    lock_key = f"{settings.redis_key_namespace}:sync-lock:{user_id}"
    lock_value = secrets.token_urlsafe(24)
    acquired = await redis.set(
        lock_key,
        lock_value,
        nx=True,
        ex=settings.sync_lock_ttl_seconds,
    )
    if not acquired:
        await redis.aclose()
        return {"status": "skipped", "reason": "sync_already_running"}
    renewal = asyncio.create_task(
        _renew_sync_lock(
            redis,
            lock_key,
            lock_value,
            settings.sync_lock_ttl_seconds,
        )
    )
    try:
        async with async_session_factory() as session:
            clients = GoogleClientFactory(
                session=session,
                user_id=user_id,
                settings=settings,
                cipher=TokenCipher(settings.token_encryption_key),
            )
            indexer = WorkspaceIndexer(
                session,
                embedding_provider_from_settings(settings),
            )
            return await WorkspaceSyncService(
                session, clients, indexer, settings
            ).sync_user(user_id)
    finally:
        renewal.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await renewal
        except Exception as exc:
            logger.warning("Sync lock renewal failed: %s", type(exc).__name__)
        try:
            await _release_sync_lock(redis, lock_key, lock_value)
        except Exception as exc:
            logger.warning("Sync lock release failed: %s", type(exc).__name__)
        await redis.aclose()


async def _enqueue_connected_users() -> dict[str, int]:
    async with async_session_factory() as session:
        user_ids = list(
            (await session.scalars(select(GoogleCredential.user_id).distinct())).all()
        )
    for user_id in user_ids:
        sync_user_task.apply_async(
            args=[str(user_id)],
            expires=get_settings().sync_lock_ttl_seconds,
        )
    return {"queued_users": len(user_ids)}


async def _renew_sync_lock(
    redis: Redis,
    lock_key: str,
    lock_value: str,
    ttl_seconds: int,
) -> None:
    interval = max(1, ttl_seconds // 3)
    while True:
        await asyncio.sleep(interval)
        renewed = await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1,
            lock_key,
            lock_value,
            ttl_seconds,
        )
        if not renewed:
            return


async def _release_sync_lock(
    redis: Redis,
    lock_key: str,
    lock_value: str,
) -> bool:
    return bool(
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            lock_value,
        )
    )
