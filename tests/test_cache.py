from fakeredis.aioredis import FakeRedis

from app.services import cache


async def test_get_many_cached_returns_empty_for_no_redis() -> None:
    result = await cache.get_many_cached(None, ["a", "b"])
    assert result == {}


async def test_set_many_cached_is_a_noop_for_no_redis() -> None:
    await cache.set_many_cached(None, {"a": 1}, ttl_seconds=60)


async def test_set_then_get_many_cached_round_trips() -> None:
    redis = FakeRedis()

    await cache.set_many_cached(
        redis, {"key:1": {"name": "Tritanium"}, "key:2": {"name": "Pyerite"}}, ttl_seconds=60
    )
    result = await cache.get_many_cached(redis, ["key:1", "key:2", "key:3"])

    assert result == {"key:1": {"name": "Tritanium"}, "key:2": {"name": "Pyerite"}}


async def test_get_many_cached_empty_keys_short_circuits() -> None:
    redis = FakeRedis()
    assert await cache.get_many_cached(redis, []) == {}


async def test_cached_value_expires_after_ttl() -> None:
    redis = FakeRedis()
    await cache.set_many_cached(redis, {"key:1": "value"}, ttl_seconds=60)

    ttl = await redis.ttl("key:1")
    assert 0 < ttl <= 60
