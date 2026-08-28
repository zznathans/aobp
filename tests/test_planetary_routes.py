import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from tests.test_blueprints_routes import _log_in

TRITANIUM_TYPE_ID = 34
SUPERCONDUCTOR_TYPE_ID = 9838
COOLANT_TYPE_ID = 9840


async def _seed_schematics(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.sde_types.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "group_id": 18, "published": True},
            {
                "_id": SUPERCONDUCTOR_TYPE_ID,
                "name": "Superconductors",
                "group_id": 1041,
                "published": True,
            },
            {"_id": COOLANT_TYPE_ID, "name": "Coolant", "group_id": 1034, "published": True},
        ]
    )
    await mongo_db.sde_planet_schematics.insert_many(
        [
            {
                "_id": 65,
                "name": "Superconductors",
                "cycle_time_seconds": 3600,
                "output": {"type_id": SUPERCONDUCTOR_TYPE_ID, "quantity": 5},
                "inputs": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 40}],
            },
            {
                "_id": 66,
                "name": "Coolant",
                "cycle_time_seconds": 1800,
                "output": {"type_id": COOLANT_TYPE_ID, "quantity": 10},
                "inputs": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 20}],
            },
        ]
    )
    await mongo_db.market_prices.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "average_price": 5.0},
            {"_id": SUPERCONDUCTOR_TYPE_ID, "average_price": 1000.0},
            {"_id": COOLANT_TYPE_ID, "average_price": 50.0},
        ]
    )


@respx.mock
async def test_planetary_list_groups_by_tier_and_shows_profit(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_schematics(mongo_db)

    response = client.get("/planetary")

    assert response.status_code == 200
    assert "Tier 2 - Refined Commodities" in response.text
    assert "Tier 4 - Advanced Commodities" in response.text
    assert "Superconductors" in response.text
    assert "Coolant" in response.text
    assert "Tritanium" in response.text
    tier2_index = response.text.index("Tier 2 - Refined Commodities")
    tier4_index = response.text.index("Tier 4 - Advanced Commodities")
    assert tier2_index < tier4_index


@respx.mock
async def test_planetary_list_empty(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/planetary")

    assert response.status_code == 200
    assert "No planetary schematics found" in response.text
