import respx
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.services import market_prices


@respx.mock
async def test_refresh_market_prices_upserts_and_updates(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    respx.get(f"{test_settings.esi_base_url}/markets/prices").mock(
        return_value=Response(
            200,
            json=[{"type_id": 34, "adjusted_price": 5.12, "average_price": 5.5}],
        )
    )

    upserted = await market_prices.refresh_market_prices(mongo_db, test_settings)
    assert upserted == 1

    price = await market_prices.get_market_price(mongo_db, 34)
    assert price is not None
    assert price["adjusted_price"] == 5.12
    assert price["average_price"] == 5.5

    respx.routes.clear()
    respx.get(f"{test_settings.esi_base_url}/markets/prices").mock(
        return_value=Response(
            200,
            json=[{"type_id": 34, "adjusted_price": 6.0, "average_price": 6.5}],
        )
    )
    await market_prices.refresh_market_prices(mongo_db, test_settings)

    updated = await market_prices.get_market_price(mongo_db, 34)
    assert updated is not None
    assert updated["adjusted_price"] == 6.0


async def test_list_market_prices_filters_by_type_ids(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.market_prices.insert_many(
        [
            {"_id": 34, "adjusted_price": 5.0, "average_price": None},
            {"_id": 35, "adjusted_price": 10.0, "average_price": None},
        ]
    )

    all_prices = await market_prices.list_market_prices(mongo_db)
    assert {doc["_id"] for doc in all_prices} == {34, 35}

    filtered = await market_prices.list_market_prices(mongo_db, {34})
    assert [doc["_id"] for doc in filtered] == [34]


async def test_get_market_price_returns_none_when_missing(
    mongo_db: AsyncMongoMockClient,
) -> None:
    assert await market_prices.get_market_price(mongo_db, 999) is None
