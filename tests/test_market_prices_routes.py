import respx
from fastapi.testclient import TestClient
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings


async def test_list_prices_returns_seeded_docs(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await mongo_db.market_prices.insert_many(
        [
            {"_id": 34, "adjusted_price": 5.0, "average_price": 5.5},
            {"_id": 35, "adjusted_price": 10.0, "average_price": None},
        ]
    )

    response = client.get("/market-prices")

    assert response.status_code == 200
    assert {doc["_id"] for doc in response.json()} == {34, 35}


async def test_list_prices_filters_by_type_ids(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await mongo_db.market_prices.insert_many(
        [
            {"_id": 34, "adjusted_price": 5.0, "average_price": 5.5},
            {"_id": 35, "adjusted_price": 10.0, "average_price": None},
        ]
    )

    response = client.get("/market-prices", params={"type_ids": "34"})

    assert response.status_code == 200
    assert [doc["_id"] for doc in response.json()] == [34]


async def test_get_price_returns_404_when_missing(client: TestClient) -> None:
    response = client.get("/market-prices/999")
    assert response.status_code == 404


async def test_get_price_returns_doc(client: TestClient, mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.market_prices.insert_one(
        {"_id": 34, "adjusted_price": 5.0, "average_price": None}
    )

    response = client.get("/market-prices/34")

    assert response.status_code == 200
    assert response.json()["_id"] == 34


async def test_refresh_rejects_missing_api_key(client: TestClient) -> None:
    response = client.post("/market-prices/refresh")
    assert response.status_code == 401


async def test_refresh_rejects_wrong_api_key(client: TestClient) -> None:
    response = client.post("/market-prices/refresh", headers={"X-Api-Key": "wrong"})
    assert response.status_code == 401


@respx.mock
async def test_refresh_upserts_with_correct_api_key(
    client: TestClient, test_settings: Settings
) -> None:
    test_settings.market_prices_refresh_api_key = "test-key"
    respx.get(f"{test_settings.esi_base_url}/markets/prices").mock(
        return_value=Response(
            200,
            json=[{"type_id": 34, "adjusted_price": 5.0, "average_price": None}],
        )
    )

    response = client.post("/market-prices/refresh", headers={"X-Api-Key": "test-key"})

    assert response.status_code == 200
    assert response.json() == {"upserted": 1}
