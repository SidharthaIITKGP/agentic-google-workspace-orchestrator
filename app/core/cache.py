import json
import math
from typing import Any

from pydantic import JsonValue
from redis.asyncio import ConnectionPool, Redis


class RedisCache:
    """Lifecycle-managed Redis access with namespaced JSON operations."""

    def __init__(
        self,
        redis_url: str,
        key_namespace: str,
        timeout_seconds: float,
    ) -> None:
        namespace = key_namespace.strip().strip(":")
        if not namespace:
            raise ValueError("Redis key namespace must not be empty")

        self._redis_url = redis_url
        self._key_namespace = namespace
        self._timeout_seconds = timeout_seconds
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None

    async def start(self) -> None:
        """Create the lazy client and pool without performing network I/O."""
        if self._client is not None:
            return

        self._pool = ConnectionPool.from_url(
            self._redis_url,
            decode_responses=True,
            socket_connect_timeout=self._timeout_seconds,
            socket_timeout=self._timeout_seconds,
            health_check_interval=30,
        )
        self._client = Redis(connection_pool=self._pool)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None

    async def ping(self) -> bool:
        return bool(await self._require_client().ping())

    async def get_json(self, key: str) -> JsonValue | None:
        raw_value = await self._require_client().get(self._namespaced_key(key))
        if raw_value is None:
            return None
        try:
            return json.loads(
                raw_value,
                parse_constant=lambda constant: _reject_non_finite_number(constant),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Cached value is not valid JSON") from exc

    async def set_json(self, key: str, value: JsonValue, ttl_seconds: int) -> None:
        if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")

        _validate_json_value(value)
        try:
            payload = json.dumps(value, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be JSON-serializable") from exc

        await self._require_client().set(
            self._namespaced_key(key),
            payload,
            ex=ttl_seconds,
        )

    async def delete(self, key: str) -> bool:
        return bool(await self._require_client().delete(self._namespaced_key(key)))

    def _namespaced_key(self, key: str) -> str:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("cache key must be a non-empty string")
        return f"{self._key_namespace}:{key}"

    def _require_client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("Redis cache has not been started")
        return self._client


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_value(item)
        return
    raise ValueError("value must contain only JSON-compatible types")


def _reject_non_finite_number(constant: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {constant}")
