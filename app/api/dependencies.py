from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import RedisCache
from app.db.session import get_db_session

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_redis_cache(request: Request) -> RedisCache:
    return request.app.state.redis_cache


RedisCacheDependency = Annotated[RedisCache, Depends(get_redis_cache)]


async def get_current_user_id(
    request: Request,
    cache: RedisCacheDependency,
) -> UUID:
    session_id = request.cookies.get("workspace_session")
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session_data = await cache.get_json(f"session:{session_id}")
    if not isinstance(session_data, dict) or not isinstance(session_data.get("user_id"), str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid")
    try:
        return UUID(session_data["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid") from exc


CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]
