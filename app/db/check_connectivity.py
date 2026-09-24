import asyncio

from sqlalchemy import text

from app.core.cache import RedisCache
from app.core.config import get_settings
from app.db.session import engine


async def check_connectivity() -> None:
    settings = get_settings()
    cache = RedisCache(
        redis_url=settings.redis_url,
        key_namespace=settings.redis_key_namespace,
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    await cache.start()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        if not await cache.ping():
            raise ConnectionError("Redis PING did not succeed")
        print("postgresql: ok")
        print("redis: ok")
    finally:
        await cache.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_connectivity())
