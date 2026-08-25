from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.services import cache, esi, sde


async def resolve_location_names(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    location_ids: set[int],
) -> dict[int, str | None]:
    cache_keys = {
        location_id: sde.cache_key("location_name", location_id) for location_id in location_ids
    }
    cached = await cache.get_many_cached(redis, list(cache_keys.values()))
    resolved: dict[int, str | None] = {
        location_id: cached[key] for location_id, key in cache_keys.items() if key in cached
    }

    remaining = location_ids - resolved.keys()
    if remaining:
        mongo_docs = await db.location_names.find(
            {"_id": {"$in": list(remaining)}, "name": {"$ne": None}}
        ).to_list(None)
        newly_resolved = {doc["_id"]: doc["name"] for doc in mongo_docs}
        resolved.update(newly_resolved)
        await cache.set_many_cached(
            redis,
            {cache_keys[loc_id]: name for loc_id, name in newly_resolved.items()},
            settings.redis_cache_ttl_seconds,
        )

    for location_id in location_ids - resolved.keys():
        name = await esi.get_location_name(settings, access_token, location_id)
        resolved[location_id] = name
        # Only persist successful resolutions - a failed lookup (e.g. missing scope or no
        # docking access) should be retried next time rather than cached as a permanent None.
        if name is not None:
            await db.location_names.update_one(
                {"_id": location_id},
                {"$set": {"name": name, "cached_at": datetime.now(UTC).replace(tzinfo=None)}},
                upsert=True,
            )
            await cache.set_many_cached(
                redis, {cache_keys[location_id]: name}, settings.redis_cache_ttl_seconds
            )

    return resolved
