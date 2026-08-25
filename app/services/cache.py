import json
from typing import Any

from redis import RedisError
from redis.asyncio import Redis


async def get_many_cached(redis: Redis | None, keys: list[str]) -> dict[str, Any]:
    if redis is None or not keys:
        return {}

    try:
        raw_values = await redis.mget(keys)
    except RedisError:
        return {}

    return {
        key: json.loads(raw) for key, raw in zip(keys, raw_values, strict=True) if raw is not None
    }


async def set_many_cached(redis: Redis | None, items: dict[str, Any], ttl_seconds: int) -> None:
    if redis is None or not items:
        return

    try:
        pipeline = redis.pipeline(transaction=False)
        for key, value in items.items():
            pipeline.set(key, json.dumps(value), ex=ttl_seconds)
        await pipeline.execute()
    except RedisError:
        pass
