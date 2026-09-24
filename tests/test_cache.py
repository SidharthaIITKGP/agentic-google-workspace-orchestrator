import asyncio
from typing import Any, cast

import pytest

from app.core.cache import RedisCache


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)

    async def ping(self) -> bool:
        return True


def make_cache(client: FakeRedis) -> RedisCache:
    cache = RedisCache(
        redis_url="redis://localhost:6379/0",
        key_namespace="test",
        timeout_seconds=1,
    )
    cache._client = cast(Any, client)
    return cache


def test_json_cache_round_trip_ttl_and_delete() -> None:
    async def exercise() -> None:
        fake_redis = FakeRedis()
        cache = make_cache(fake_redis)
        value = {"items": [1, "two", True, None]}

        await cache.set_json("result", value, ttl_seconds=30)

        assert await cache.get_json("result") == value
        assert fake_redis.ttls["test:result"] == 30
        assert await cache.delete("result") is True
        assert await cache.get_json("result") is None

    asyncio.run(exercise())


@pytest.mark.parametrize("value", [object(), ("tuple",), float("nan")])
def test_json_cache_rejects_non_json_values(value: object) -> None:
    async def exercise() -> None:
        cache = make_cache(FakeRedis())
        with pytest.raises(ValueError):
            await cache.set_json("invalid", cast(Any, value), ttl_seconds=30)

    asyncio.run(exercise())


@pytest.mark.parametrize("ttl_seconds", [0, -1, True])
def test_json_cache_requires_positive_ttl(ttl_seconds: int) -> None:
    async def exercise() -> None:
        cache = make_cache(FakeRedis())
        with pytest.raises(ValueError, match="positive integer"):
            await cache.set_json("result", {"ok": True}, ttl_seconds=ttl_seconds)

    asyncio.run(exercise())
