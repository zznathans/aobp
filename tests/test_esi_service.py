import respx
from httpx import Response
from prometheus_client import Histogram

from app.core.config import Settings
from app.services import esi


def _histogram_count(histogram: Histogram, **labels: str) -> float:
    for sample in next(iter(histogram.collect())).samples:
        if sample.name.endswith("_count") and sample.labels == labels:
            return sample.value
    return 0.0


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
async def test_get_location_details_uses_station_endpoint_for_npc_stations() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/stations/60003760").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4", "system_id": 30000142})
    )

    details = await esi.get_location_details(settings, "token", 60003760)

    assert details == esi.LocationDetails(name="Jita IV - Moon 4", system_id=30000142)


@respx.mock
async def test_get_location_details_uses_structure_endpoint_for_player_structures() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/structures/1000000000123").mock(
        return_value=Response(200, json={"name": "My Citadel", "system_id": 30000142})
    )

    details = await esi.get_location_details(settings, "token", 1000000000123)

    assert details == esi.LocationDetails(name="My Citadel", system_id=30000142)


@respx.mock
async def test_get_location_details_returns_empty_on_forbidden() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/structures/1000000000123").mock(
        return_value=Response(403, json={"error": "no access"})
    )

    details = await esi.get_location_details(settings, "token", 1000000000123)

    assert details == esi.LocationDetails(name=None, system_id=None)


@respx.mock
async def test_get_system_security_status_returns_value() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/systems/30000142").mock(
        return_value=Response(200, json={"security_status": 0.9459991455078125})
    )

    status = await esi.get_system_security_status(settings, 30000142)

    assert status == 0.9459991455078125


@respx.mock
async def test_get_system_security_status_returns_none_on_error() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/systems/30000142").mock(
        return_value=Response(500, json={"error": "boom"})
    )

    status = await esi.get_system_security_status(settings, 30000142)

    assert status is None


@respx.mock
async def test_get_market_prices_records_request_duration() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/markets/prices").mock(return_value=Response(200, json=[]))
    count_before = _histogram_count(esi.ESI_REQUEST_DURATION, endpoint="markets/prices")

    await esi.get_market_prices(settings)

    assert _histogram_count(esi.ESI_REQUEST_DURATION, endpoint="markets/prices") == count_before + 1


@respx.mock
async def test_get_location_details_records_error_on_forbidden() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/structures/1000000000123").mock(
        return_value=Response(403, json={"error": "no access"})
    )
    errors_before = esi.ESI_REQUEST_ERRORS.labels(endpoint="universe/structures")._value.get()

    await esi.get_location_details(settings, "token", 1000000000123)

    assert (
        esi.ESI_REQUEST_ERRORS.labels(endpoint="universe/structures")._value.get()
        == errors_before + 1
    )
