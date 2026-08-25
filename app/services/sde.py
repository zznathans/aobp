from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.services import cache


def cache_key(prefix: str, value: int) -> str:
    return f"{prefix}:{value}"


async def cached_docs_by_id(
    collection: AsyncIOMotorCollection,
    redis: Redis | None,
    settings: Settings,
    key_prefix: str,
    ids: set[int],
) -> dict[int, dict[str, object]]:
    cache_keys = {doc_id: cache_key(key_prefix, doc_id) for doc_id in ids}
    cached = await cache.get_many_cached(redis, list(cache_keys.values()))
    found: dict[int, dict[str, object]] = {
        doc_id: cached[key] for doc_id, key in cache_keys.items() if key in cached
    }

    missing_ids = ids - found.keys()
    if missing_ids:
        docs = await collection.find({"_id": {"$in": list(missing_ids)}}).to_list(None)
        for doc in docs:
            found[doc["_id"]] = doc
        await cache.set_many_cached(
            redis,
            {cache_keys[doc["_id"]]: doc for doc in docs},
            settings.redis_cache_ttl_seconds,
        )

    return found


async def type_docs(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    type_ids: set[int],
) -> dict[int, dict[str, object]]:
    return await cached_docs_by_id(db.sde_types, redis, settings, "sde_type", type_ids)


async def blueprint_docs(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    type_ids: set[int],
) -> dict[int, dict[str, object]]:
    return await cached_docs_by_id(db.sde_blueprints, redis, settings, "sde_blueprint", type_ids)
