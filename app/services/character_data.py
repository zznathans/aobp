from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.services import esi, esi_cache

_ASSETS_CACHE_TTL_SECONDS = 60 * 60
_BLUEPRINTS_CACHE_TTL_SECONDS = 60 * 60
_INDUSTRY_JOBS_CACHE_TTL_SECONDS = 60 * 60


async def get_character_assets(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    character_id: int,
) -> list[esi.AssetEntry]:
    return await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="assets",
        cache_key_prefix="character_assets",
        character_id=character_id,
        ttl_seconds=_ASSETS_CACHE_TTL_SECONDS,
        entry_type=esi.AssetEntry,
        fetch=lambda: esi.get_character_assets(settings, access_token, character_id),
    )


async def get_character_blueprints(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    character_id: int,
) -> list[esi.BlueprintEntry]:
    return await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="blueprints",
        cache_key_prefix="character_blueprints",
        character_id=character_id,
        ttl_seconds=_BLUEPRINTS_CACHE_TTL_SECONDS,
        entry_type=esi.BlueprintEntry,
        fetch=lambda: esi.get_character_blueprints(settings, access_token, character_id),
    )


async def get_character_industry_jobs(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    character_id: int,
) -> list[esi.IndustryJobEntry]:
    return await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="industry_jobs",
        cache_key_prefix="character_industry_jobs",
        character_id=character_id,
        ttl_seconds=_INDUSTRY_JOBS_CACHE_TTL_SECONDS,
        entry_type=esi.IndustryJobEntry,
        fetch=lambda: esi.get_character_industry_jobs(settings, access_token, character_id),
    )
