from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.services import cache

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    T = TypeVar("T", bound=DataclassInstance)
else:
    T = TypeVar("T")


async def cached_character_list(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    *,
    collection_name: str,
    cache_key_prefix: str,
    character_id: int,
    ttl_seconds: int,
    entry_type: type[T],
    fetch: Callable[[], Awaitable[list[T]]],
) -> list[T]:
    cache_key = f"{cache_key_prefix}:{character_id}"
    cached = await cache.get_many_cached(redis, [cache_key])
    if cache_key in cached:
        return [entry_type(**entry) for entry in cached[cache_key]]

    entries = await fetch()
    entry_dicts = [asdict(entry) for entry in entries]

    collection = db[collection_name]
    await collection.delete_many({"character_id": character_id})
    if entry_dicts:
        await collection.insert_many(
            [
                {
                    "character_id": character_id,
                    "cached_at": datetime.now(UTC).replace(tzinfo=None),
                    **entry_dict,
                }
                for entry_dict in entry_dicts
            ]
        )

    await cache.set_many_cached(redis, {cache_key: entry_dicts}, ttl_seconds)

    return entries
