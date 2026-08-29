from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar, cast

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.models.character import CharacterDocument
from app.services import esi, esi_cache

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    T = TypeVar("T", bound=DataclassInstance)
else:
    T = TypeVar("T")

_ASSETS_CACHE_TTL_SECONDS = 60 * 60
_BLUEPRINTS_CACHE_TTL_SECONDS = 60 * 60
_INDUSTRY_JOBS_CACHE_TTL_SECONDS = 60 * 60


def corp_data_connected(character: CharacterDocument) -> bool:
    return character.corp_refresh_token is not None


async def _corp_list_or_none(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    *,
    collection_name: str,
    cache_key_prefix: str,
    corporation_id: int,
    ttl_seconds: int,
    entry_type: type[T],
    fetch: Callable[[], Awaitable[list[T]]],
) -> list[T] | None:
    """None means this character can't use this endpoint right now - either a 403
    (valid token, but missing the corp role the endpoint requires, e.g. Director
    for assets/blueprints) or a 401 (the corp token doesn't actually carry the
    scope this endpoint needs, e.g. EVE_SSO_CORP_SCOPES was misconfigured when the
    character connected). [] means the fetch succeeded and the corp just doesn't
    own anything of that kind."""
    try:
        return await esi_cache.cached_corporation_list(
            db,
            redis,
            collection_name=collection_name,
            cache_key_prefix=cache_key_prefix,
            corporation_id=corporation_id,
            ttl_seconds=ttl_seconds,
            entry_type=entry_type,
            fetch=fetch,
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (401, 403):
            return None
        raise


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


async def get_corporation_assets(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    corporation_id: int,
) -> list[esi.AssetEntry] | None:
    return await _corp_list_or_none(
        db,
        redis,
        collection_name="corp_assets",
        cache_key_prefix="corporation_assets",
        corporation_id=corporation_id,
        ttl_seconds=_ASSETS_CACHE_TTL_SECONDS,
        entry_type=esi.AssetEntry,
        fetch=lambda: esi.get_corporation_assets(settings, access_token, corporation_id),
    )


async def get_corporation_blueprints(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    corporation_id: int,
) -> list[esi.BlueprintEntry] | None:
    return await _corp_list_or_none(
        db,
        redis,
        collection_name="corp_blueprints",
        cache_key_prefix="corporation_blueprints",
        corporation_id=corporation_id,
        ttl_seconds=_BLUEPRINTS_CACHE_TTL_SECONDS,
        entry_type=esi.BlueprintEntry,
        fetch=lambda: esi.get_corporation_blueprints(settings, access_token, corporation_id),
    )


async def get_corporation_industry_jobs(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    access_token: str,
    corporation_id: int,
) -> list[esi.IndustryJobEntry] | None:
    return await _corp_list_or_none(
        db,
        redis,
        collection_name="corp_industry_jobs",
        cache_key_prefix="corporation_industry_jobs",
        corporation_id=corporation_id,
        ttl_seconds=_INDUSTRY_JOBS_CACHE_TTL_SECONDS,
        entry_type=esi.IndustryJobEntry,
        fetch=lambda: esi.get_corporation_industry_jobs(settings, access_token, corporation_id),
    )


async def _merge_corp(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
    personal: list[T],
    fetch_corp: Callable[[str, int], Awaitable[list[T] | None]],
) -> tuple[list[T], bool]:
    """Concatenates personal + corp entries when corp data is connected and the
    character has the role the endpoint requires. Returns whether corp data was
    actually merged in, so routes can show an "includes corporation data" note."""
    if not corp_data_connected(character):
        return personal, False

    corp_entries = await fetch_corp(
        cast(str, character.corp_access_token), cast(int, character.corporation_id)
    )
    if corp_entries is None:
        return personal, False
    return [*personal, *corp_entries], True


async def get_merged_assets(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
) -> tuple[list[esi.AssetEntry], bool]:
    personal = await get_character_assets(
        db, redis, settings, character.access_token, character.character_id
    )
    return await _merge_corp(
        db,
        redis,
        settings,
        character,
        personal,
        lambda token, corp_id: get_corporation_assets(db, redis, settings, token, corp_id),
    )


async def get_merged_blueprints(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
) -> tuple[list[esi.BlueprintEntry], bool]:
    personal = await get_character_blueprints(
        db, redis, settings, character.access_token, character.character_id
    )
    return await _merge_corp(
        db,
        redis,
        settings,
        character,
        personal,
        lambda token, corp_id: get_corporation_blueprints(db, redis, settings, token, corp_id),
    )


async def get_merged_industry_jobs(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
) -> tuple[list[esi.IndustryJobEntry], bool]:
    personal = await get_character_industry_jobs(
        db, redis, settings, character.access_token, character.character_id
    )
    return await _merge_corp(
        db,
        redis,
        settings,
        character,
        personal,
        lambda token, corp_id: get_corporation_industry_jobs(db, redis, settings, token, corp_id),
    )
