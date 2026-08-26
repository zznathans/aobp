from mongomock_motor import AsyncMongoMockClient

from app.services import db_gauges


async def test_refresh_db_gauges_reflects_document_counts() -> None:
    client = AsyncMongoMockClient()
    db = client["eve-build"]
    await db.characters.insert_many([{"_id": 1}, {"_id": 2}])
    await db.market_prices.insert_many([{"_id": 34}, {"_id": 35}, {"_id": 36}])

    await db_gauges.refresh_db_gauges(db)

    assert db_gauges.CHARACTERS_TRACKED._value.get() == 2
    assert db_gauges.MARKET_PRICES_CACHED._value.get() == 3
