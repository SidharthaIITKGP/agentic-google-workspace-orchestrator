from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.approvals import router as approvals_router
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.query import router as query_router
from app.api.routes.readiness import router as readiness_router
from app.core.cache import RedisCache
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    cache = RedisCache(
        redis_url=settings.redis_url,
        key_namespace=settings.redis_key_namespace,
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    await cache.start()
    application.state.redis_cache = cache
    try:
        yield
    finally:
        await cache.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health_router)
app.include_router(readiness_router)
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(approvals_router)
