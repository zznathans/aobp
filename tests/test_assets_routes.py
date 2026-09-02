from urllib.parse import parse_qs, urlparse

import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from tests.conftest import make_access_token

CHARACTER_ID = 555
TRITANIUM_TYPE_ID = 34
PYERITE_TYPE_ID = 35
VELDSPAR_TYPE_ID = 1230  # an ore, not a mineral - used to prove the two tables stay separate
DATACORE_TYPE_ID = 20424  # Datacore - Amarrian Starship Engineering
DECRYPTOR_TYPE_ID = 34201  # Accelerant Decryptor
WATER_TYPE_ID = 3645  # a P1 planetary commodity
STATION_ID = 60003760
SECOND_STATION_ID = 60003761


def _log_in(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, jwk = rsa_key_pair
    login_response = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    access_token = make_access_token(
        private_key, character_id=CHARACTER_ID, character_name="Alt Pilot"
    )
    respx.post(test_settings.eve_sso_token_url).mock(
        return_value=Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "refresh-token-value",
                "expires_in": 1200,
            },
        )
    )
    respx.get(test_settings.eve_sso_jwks_url).mock(return_value=Response(200, json={"keys": [jwk]}))

    client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )


def _mock_assets(settings: Settings) -> None:
    respx.get(f"{settings.esi_base_url}/characters/{CHARACTER_ID}/assets", params={"page": 1}).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "1"},
            json=[
                {
                    "item_id": 1,
                    "type_id": TRITANIUM_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 100,
                    "is_singleton": False,
                },
                {
                    "item_id": 2,
                    "type_id": PYERITE_TYPE_ID,
                    "location_id": SECOND_STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 50,
                    "is_singleton": False,
                },
                {
                    "item_id": 3,
                    "type_id": VELDSPAR_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 999,
                    "is_singleton": False,
                },
                {
                    "item_id": 4,
                    "type_id": DATACORE_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 10,
                    "is_singleton": False,
                },
                {
                    "item_id": 5,
                    "type_id": DECRYPTOR_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 3,
                    "is_singleton": False,
                },
                {
                    "item_id": 6,
                    "type_id": WATER_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 500,
                    "is_singleton": False,
                },
            ],
        )
    )


def _mock_station_names(settings: Settings) -> None:
    respx.get(f"{settings.esi_base_url}/universe/stations/{STATION_ID}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4"})
    )
    respx.get(f"{settings.esi_base_url}/universe/stations/{SECOND_STATION_ID}").mock(
        return_value=Response(200, json={"name": "Amarr VIII - Emperor Family Academy"})
    )


async def _seed_sde_and_prices(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.sde_types.insert_many(
        [
            {
                "_id": TRITANIUM_TYPE_ID,
                "name": "Tritanium",
                "group_id": 18,
                "category_id": 4,
                "published": True,
                "volume": 0.01,
            },
            {
                # Priced much higher per-unit than Tritanium but stacks to less total volume,
                # so a value-descending sort would rank it first - a volume-descending sort
                # (what's under test) must rank Tritanium first instead.
                "_id": PYERITE_TYPE_ID,
                "name": "Pyerite",
                "group_id": 18,
                "category_id": 4,
                "published": True,
                "volume": 0.01,
            },
            {
                "_id": VELDSPAR_TYPE_ID,
                "name": "Veldspar",
                "group_id": 450,
                "category_id": 25,
                "published": True,
                "volume": 0.1,
            },
            {
                "_id": DATACORE_TYPE_ID,
                "name": "Datacore - Amarrian Starship Engineering",
                "group_id": 333,
                "category_id": 17,
                "published": True,
                "volume": 0.1,
            },
            {
                "_id": DECRYPTOR_TYPE_ID,
                "name": "Accelerant Decryptor",
                "group_id": 1304,
                "category_id": 35,
                "published": True,
                "volume": 0.01,
            },
            {
                "_id": WATER_TYPE_ID,
                "name": "Water",
                "group_id": 1042,
                "category_id": 43,
                "published": True,
                "volume": 0.38,
            },
        ]
    )
    await mongo_db.market_prices.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "adjusted_price": 5.0, "average_price": 5.0},
            {"_id": PYERITE_TYPE_ID, "adjusted_price": 50.0, "average_price": 50.0},
            {"_id": VELDSPAR_TYPE_ID, "adjusted_price": 1.0, "average_price": 1.0},
            {"_id": DATACORE_TYPE_ID, "adjusted_price": 100.0, "average_price": 100.0},
            {"_id": DECRYPTOR_TYPE_ID, "adjusted_price": 200.0, "average_price": 200.0},
            {"_id": WATER_TYPE_ID, "adjusted_price": 3.0, "average_price": 3.0},
        ]
    )


@respx.mock
async def test_list_assets_shows_totals_and_category_tables(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    _mock_assets(test_settings)

    response = client.get("/assets")

    assert response.status_code == 200
    # overview never resolves location names - only counts, no ESI station lookups
    assert "Tritanium" in response.text
    assert "Pyerite" in response.text
    assert "Veldspar" in response.text
    assert "Datacore - Amarrian Starship Engineering" in response.text
    assert "Accelerant Decryptor" in response.text
    assert "Water" in response.text
    assert "Minerals" in response.text
    assert "Planetary Materials" in response.text
    assert "Ore" in response.text
    assert "Datacores" in response.text
    assert "Decrypters" in response.text
    assert f'href="/assets/{TRITANIUM_TYPE_ID}"' in response.text
    assert f'href="/assets/{VELDSPAR_TYPE_ID}"' in response.text
    assert f'href="/assets/{WATER_TYPE_ID}"' in response.text
    # Veldspar is an ore (category 25), not a mineral - it must appear once, under Ore,
    # not also in the Minerals table.
    minerals_heading_index = response.text.index("Minerals")
    ore_heading_index = response.text.index("Ore")
    veldspar_index = response.text.index("Veldspar")
    assert minerals_heading_index < ore_heading_index < veldspar_index
    # Water is a planetary commodity (category 43), not a mineral - it must show up under
    # Planetary Materials, which shares the Minerals column and so renders right after it.
    planetary_heading_index = response.text.index("Planetary Materials")
    water_index = response.text.index("Water")
    assert minerals_heading_index < planetary_heading_index < water_index
    # Within Minerals, rows must sort by total volume descending, not value: Pyerite is priced
    # far higher per unit (500 vs 2,500 ISK total) but has half Tritanium's total volume.
    tritanium_index = response.text.index("Tritanium")
    pyerite_index = response.text.index("Pyerite")
    assert tritanium_index < pyerite_index < planetary_heading_index
    # 100*5 + 50*50 + 999*1 + 10*100 + 3*200 + 500*3 = 500+2,500+999+1,000+600+1,500 = 7,099 ISK
    assert "7.1K ISK" in response.text
    # 2 distinct locations
    assert '<div class="value">2</div>' in response.text
    # 100 + 50 + 999 + 10 + 3 + 500 = 1,662 total items
    assert "1,662" in response.text
    # No compressed ore owned in this fixture - the table must not render at all, not even
    # as an empty "None found" box.
    assert "Compressed Ore" not in response.text


@respx.mock
async def test_list_assets_compressed_ore_shown_above_ore_only_when_owned(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    compressed_veldspar_type_id = 62529

    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    await mongo_db.sde_types.insert_one(
        {
            "_id": compressed_veldspar_type_id,
            "name": "Compressed Veldspar",
            "group_id": 450,
            "category_id": 25,
            "published": True,
            "volume": 0.15,
        }
    )
    await mongo_db.market_prices.insert_one(
        {"_id": compressed_veldspar_type_id, "adjusted_price": 2.0, "average_price": 2.0}
    )
    respx.get(
        f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/assets", params={"page": 1}
    ).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "1"},
            json=[
                {
                    "item_id": 1,
                    "type_id": VELDSPAR_TYPE_ID,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 999,
                    "is_singleton": False,
                },
                {
                    "item_id": 2,
                    "type_id": compressed_veldspar_type_id,
                    "location_id": STATION_ID,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 50,
                    "is_singleton": False,
                },
            ],
        )
    )

    response = client.get("/assets")

    assert response.status_code == 200
    assert "Compressed Veldspar" in response.text
    assert "Veldspar" in response.text
    compressed_heading_index = response.text.index("Compressed Ore")
    # search past "Compressed Ore" itself, which also contains the substring "Ore"
    ore_heading_index = response.text.index("<h2>Ore</h2>", compressed_heading_index)
    compressed_veldspar_index = response.text.index("Compressed Veldspar")
    veldspar_index = response.text.rindex("Veldspar")
    assert compressed_heading_index < compressed_veldspar_index < ore_heading_index < veldspar_index


@respx.mock
async def test_assets_dashboard_link_points_to_assets_page(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    _mock_assets(test_settings)
    respx.get(
        f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/blueprints", params={"page": 1}
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))
    respx.get(f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/industry/jobs").mock(
        return_value=Response(200, headers={"X-Pages": "1"}, json=[])
    )

    response = client.get("/")

    assert response.status_code == 200
    assert '<a class="stat-card" href="/assets">' in response.text


@respx.mock
async def test_item_detail_shows_market_data_owned_summary_and_locations(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    _mock_assets(test_settings)
    station_route = respx.get(f"{test_settings.esi_base_url}/universe/stations/{STATION_ID}")
    station_route.mock(return_value=Response(200, json={"name": "Jita IV - Moon 4"}))

    response = client.get(f"/assets/{TRITANIUM_TYPE_ID}")

    assert response.status_code == 200
    assert "Tritanium" in response.text
    assert "Jita IV - Moon 4" in response.text
    # market data: adjusted_price and average_price were both seeded at 5.0 ISK
    assert "Market data" in response.text
    assert "5 ISK" in response.text
    # owned summary: 100 units * 5 ISK = 500 ISK, 100 * 0.01 m3 = 1 m3
    assert "What you own" in response.text
    assert "100" in response.text
    assert "500 ISK" in response.text
    # Tritanium only sits at STATION_ID - if the other station got looked up too, respx would
    # raise (it's never mocked), proving the per-item page only resolves matching locations.
    assert station_route.call_count == 1
    assert f'href="/assets/locations/{STATION_ID}"' in response.text


@respx.mock
async def test_location_detail_shows_stats_and_items_at_that_location(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    _mock_assets(test_settings)
    _mock_station_names(test_settings)

    response = client.get(f"/assets/locations/{STATION_ID}")

    assert response.status_code == 200
    assert "Jita IV - Moon 4" in response.text
    # STATION_ID holds Tritanium (100), Veldspar (999), Datacore (10), Decryptor (3), Water
    # (500) - Pyerite is at SECOND_STATION_ID and must not appear here.
    assert "Tritanium" in response.text
    assert "Veldspar" in response.text
    assert "Water" in response.text
    assert "Pyerite" not in response.text
    assert f'href="/assets/{TRITANIUM_TYPE_ID}"' in response.text
    # 5 distinct item types at this location
    assert '<div class="value">5</div>' in response.text
    # 100 + 999 + 10 + 3 + 500 = 1,612 total items at this location
    assert "1,612" in response.text
    assert '<a class="btn btn-secondary back" href="/assets">' in response.text


@respx.mock
async def test_location_detail_404_for_location_with_no_assets(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_sde_and_prices(mongo_db)
    _mock_assets(test_settings)

    response = client.get("/assets/locations/999999999")

    assert response.status_code == 404


@respx.mock
async def test_item_detail_404_for_unowned_type(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    respx.get(
        f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/assets", params={"page": 1}
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))

    response = client.get(f"/assets/{TRITANIUM_TYPE_ID}")

    assert response.status_code == 404


@respx.mock
async def test_list_assets_empty_state(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    respx.get(
        f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/assets", params={"page": 1}
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))

    response = client.get("/assets")

    assert response.status_code == 200
    assert "No assets found." in response.text
