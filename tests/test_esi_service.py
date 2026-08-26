import respx
from httpx import Response

from app.core.config import Settings
from app.services import esi


@respx.mock
async def test_get_character_blueprints_merges_pages() -> None:
    settings = Settings()
    url = f"{settings.esi_base_url}/characters/123/blueprints"
    respx.get(url, params={"page": 1}).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "2"},
            json=[
                {
                    "item_id": 1,
                    "type_id": 588,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "quantity": -1,
                    "runs": -1,
                    "material_efficiency": 10,
                    "time_efficiency": 20,
                }
            ],
        )
    )
    respx.get(url, params={"page": 2}).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "2"},
            json=[
                {
                    "item_id": 2,
                    "type_id": 589,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "quantity": -2,
                    "runs": 5,
                    "material_efficiency": 0,
                    "time_efficiency": 0,
                }
            ],
        )
    )

    blueprints = await esi.get_character_blueprints(settings, "token", 123)

    assert [bp.item_id for bp in blueprints] == [1, 2]
    assert blueprints[0].type_id == 588
    assert blueprints[1].runs == 5


@respx.mock
async def test_get_market_prices_parses_entries() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/markets/prices").mock(
        return_value=Response(
            200,
            json=[
                {"type_id": 34, "adjusted_price": 5.12, "average_price": 5.5},
                {"type_id": 35, "adjusted_price": 10.0},
            ],
        )
    )

    prices = await esi.get_market_prices(settings)

    assert prices[0] == esi.MarketPriceEntry(type_id=34, adjusted_price=5.12, average_price=5.5)
    assert prices[1] == esi.MarketPriceEntry(type_id=35, adjusted_price=10.0, average_price=None)


@respx.mock
async def test_get_location_name_uses_station_endpoint_for_npc_stations() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/stations/60003760").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4"})
    )

    name = await esi.get_location_name(settings, "token", 60003760)

    assert name == "Jita IV - Moon 4"


@respx.mock
async def test_get_location_name_uses_structure_endpoint_for_player_structures() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/structures/1000000000123").mock(
        return_value=Response(200, json={"name": "My Citadel"})
    )

    name = await esi.get_location_name(settings, "token", 1000000000123)

    assert name == "My Citadel"


@respx.mock
async def test_get_location_name_returns_none_on_forbidden() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/structures/1000000000123").mock(
        return_value=Response(403, json={"error": "no access"})
    )

    name = await esi.get_location_name(settings, "token", 1000000000123)

    assert name is None
