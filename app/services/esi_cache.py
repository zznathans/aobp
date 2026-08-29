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
        try:
            return [entry_type(**entry) for entry in cached[cache_key]]
        except TypeError:
            # Cached entries were serialized before entry_type gained/dropped a field -
            # fall through to a fresh fetch (which overwrites the stale cache below)
            # instead of crashing the request on a schema mismatch.
            pass

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


async def invalidate_character_list(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    *,
    collection_name: str,
    cache_key_prefix: str,
    character_id: int,
) -> None:
    await db[collection_name].delete_many({"character_id": character_id})
    await cache.delete_cached(redis, [f"{cache_key_prefix}:{character_id}"])


async def invalidate_corporation_list(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    *,
    collection_name: str,
    cache_key_prefix: str,
    corporation_id: int,
) -> None:
    await db[collection_name].delete_many({"corporation_id": corporation_id})
    await cache.delete_cached(redis, [f"{cache_key_prefix}:{corporation_id}"])


async def cached_corporation_list(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    *,
    collection_name: str,
    cache_key_prefix: str,
    corporation_id: int,
    ttl_seconds: int,
    entry_type: type[T],
    fetch: Callable[[], Awaitable[list[T]]],
) -> list[T]:
    """Same shape as cached_character_list, but keyed/tagged by corporation_id -
    corp data is shared across every character in that corp, so a fetch triggered
    by one Director/Factory_Manager is reused by any other connected character in
    the same corp within the TTL window, rather than being cached per-character."""
    cache_key = f"{cache_key_prefix}:{corporation_id}"
    cached = await cache.get_many_cached(redis, [cache_key])
    if cache_key in cached:
        try:
            return [entry_type(**entry) for entry in cached[cache_key]]
        except TypeError:
            pass

    entries = await fetch()
    entry_dicts = [asdict(entry) for entry in entries]

    collection = db[collection_name]
    await collection.delete_many({"corporation_id": corporation_id})
    if entry_dicts:
        await collection.insert_many(
            [
                {
                    "corporation_id": corporation_id,
                    "cached_at": datetime.now(UTC).replace(tzinfo=None),
                    **entry_dict,
                }
                for entry_dict in entry_dicts
            ]
        )

    await cache.set_many_cached(redis, {cache_key: entry_dicts}, ttl_seconds)

    return entries
