import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.dependencies import DatabaseSession, RedisCacheDependency
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/ready")
async def readiness(
    session: DatabaseSession,
    cache: RedisCacheDependency,
) -> JSONResponse:
    """Verify bounded connectivity to required application dependencies."""
    timeout = get_settings().dependency_timeout_seconds
    postgresql_result, redis_result = await asyncio.gather(
        _check_postgresql(session, timeout),
        _check_redis(cache, timeout),
    )

    services = {
        "postgresql": "ok" if postgresql_result else "unavailable",
        "redis": "ok" if redis_result else "unavailable",
    }
    if all((postgresql_result, redis_result)):
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "services": services},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "services": services},
    )


async def _check_postgresql(session: DatabaseSession, timeout: float) -> bool:
    try:
        await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=timeout)
    except Exception:
        return False
    return True


async def _check_redis(cache: RedisCacheDependency, timeout: float) -> bool:
    try:
        return bool(await asyncio.wait_for(cache.ping(), timeout=timeout))
    except Exception:
        return False
