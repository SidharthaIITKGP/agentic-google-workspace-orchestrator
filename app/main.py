import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.approvals import router as approvals_router
from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.query import router as query_router
from app.api.routes.readiness import router as readiness_router
from app.api.routes.sync import router as sync_router
from app.core.cache import RedisCache
from app.core.config import get_settings
from app.retrieval.embeddings import embedding_provider_from_settings

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    cache = RedisCache(
        redis_url=settings.redis_url,
        key_namespace=settings.redis_key_namespace,
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    await cache.start()
    application.state.redis_cache = cache
    if settings.embedding_warmup_enabled:
        try:
            await asyncio.to_thread(
                embedding_provider_from_settings(settings).warmup
            )
        except Exception as exc:
            logger.warning(
                "Optional embedding model warmup failed: %s",
                type(exc).__name__,
            )
    try:
        yield
    finally:
        await cache.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(health_router)
app.include_router(readiness_router)
app.include_router(auth_router)
app.include_router(query_router)
app.include_router(approvals_router)
app.include_router(sync_router)
