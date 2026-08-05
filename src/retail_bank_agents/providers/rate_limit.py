from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis


class RedisRateLimiter:
    """Atomic fixed-window limiter; API Gateway/WAF should provide the first layer."""

    _SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
    return current
    """

    def __init__(self, redis: Redis, limit: int = 30, window_seconds: int = 60) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_seconds

    async def allow(self, customer_id: str) -> bool:
        pending = self._redis.eval(self._SCRIPT, 1, f"rate:chat:{customer_id}", str(self._window))
        count = await cast(Awaitable[int], pending)
        return int(count) <= self._limit
