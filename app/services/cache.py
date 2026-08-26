import json
from typing import Any

from prometheus_client import Counter
from redis import RedisError
from redis.asyncio import Redis

CACHE_HITS = Counter("eve_build_cache_hits_total", "Cache keys found in Redis")
CACHE_MISSES = Counter("eve_build_cache_misses_total", "Cache keys not found in Redis")
CACHE_ERRORS = Counter("eve_build_cache_errors_total", "Redis errors during a cache operation")


async def get_many_cached(redis: Redis | None, keys: list[str]) -> dict[str, Any]:
    if redis is None or not keys:
        return {}

    try:
        raw_values = await redis.mget(keys)
    except RedisError:
        CACHE_ERRORS.inc()
        return {}

    result = {
        key: json.loads(raw) for key, raw in zip(keys, raw_values, strict=True) if raw is not None
    }
    CACHE_HITS.inc(len(result))
    CACHE_MISSES.inc(len(keys) - len(result))
    return result


async def set_many_cached(redis: Redis | None, items: dict[str, Any], ttl_seconds: int) -> None:
    if redis is None or not items:
        return

    try:
        pipeline = redis.pipeline(transaction=False)
        for key, value in items.items():
            pipeline.set(key, json.dumps(value), ex=ttl_seconds)
        await pipeline.execute()
    except RedisError:
        CACHE_ERRORS.inc()
