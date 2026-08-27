from dataclasses import dataclass

from fakeredis.aioredis import FakeRedis
from mongomock_motor import AsyncMongoMockClient

from app.services import esi_cache


@dataclass(frozen=True)
class _Entry:
    item_id: int
    name: str


def _mongo_db() -> object:
    return AsyncMongoMockClient()["eve-build"]


async def test_cache_miss_fetches_persists_and_caches() -> None:
    db = _mongo_db()
    redis = FakeRedis()
    fetch_calls = 0

    async def fetch() -> list[_Entry]:
        nonlocal fetch_calls
        fetch_calls += 1
        return [_Entry(item_id=1, name="Tritanium"), _Entry(item_id=2, name="Pyerite")]

    result = await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="widgets",
        cache_key_prefix="character_widgets",
        character_id=42,
        ttl_seconds=3600,
        entry_type=_Entry,
        fetch=fetch,
    )

    assert result == [_Entry(item_id=1, name="Tritanium"), _Entry(item_id=2, name="Pyerite")]
    assert fetch_calls == 1

    docs = await db.widgets.find({"character_id": 42}).to_list(None)
    assert {(d["item_id"], d["name"]) for d in docs} == {(1, "Tritanium"), (2, "Pyerite")}
    assert all(d["character_id"] == 42 for d in docs)
    assert all("cached_at" in d for d in docs)

    cached_raw = await redis.get("character_widgets:42")
    assert cached_raw is not None


async def test_cache_hit_skips_fetch() -> None:
    db = _mongo_db()
    redis = FakeRedis()
    fetch_calls = 0

    async def fetch() -> list[_Entry]:
        nonlocal fetch_calls
        fetch_calls += 1
        return [_Entry(item_id=1, name="Tritanium")]

    first = await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="widgets",
        cache_key_prefix="character_widgets",
        character_id=7,
        ttl_seconds=3600,
        entry_type=_Entry,
        fetch=fetch,
    )
    second = await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="widgets",
        cache_key_prefix="character_widgets",
        character_id=7,
        ttl_seconds=3600,
        entry_type=_Entry,
        fetch=fetch,
    )

    assert first == second == [_Entry(item_id=1, name="Tritanium")]
    assert fetch_calls == 1


async def test_empty_fetch_result_does_not_error_and_still_caches() -> None:
    db = _mongo_db()
    redis = FakeRedis()

    async def fetch() -> list[_Entry]:
        return []

    result = await esi_cache.cached_character_list(
        db,
        redis,
        collection_name="widgets",
        cache_key_prefix="character_widgets",
        character_id=99,
        ttl_seconds=3600,
        entry_type=_Entry,
        fetch=fetch,
    )

    assert result == []
    cached_raw = await redis.get("character_widgets:99")
    assert cached_raw == "[]"


async def test_no_redis_still_fetches_and_persists() -> None:
    db = _mongo_db()

    async def fetch() -> list[_Entry]:
        return [_Entry(item_id=1, name="Tritanium")]

    result = await esi_cache.cached_character_list(
        db,
        None,
        collection_name="widgets",
        cache_key_prefix="character_widgets",
        character_id=5,
        ttl_seconds=3600,
        entry_type=_Entry,
        fetch=fetch,
    )

    assert result == [_Entry(item_id=1, name="Tritanium")]
    docs = await db.widgets.find({"character_id": 5}).to_list(None)
    assert len(docs) == 1
