import respx
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.services import locations

STATION_ID = 60003760
SYSTEM_ID = 30000142


def _mongo_db() -> object:
    return AsyncMongoMockClient()["eve-build"]


@respx.mock
async def test_resolve_location_info_fetches_name_and_security_status() -> None:
    settings = Settings()
    db = _mongo_db()
    respx.get(f"{settings.esi_base_url}/universe/stations/{STATION_ID}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4", "system_id": SYSTEM_ID})
    )
    respx.get(f"{settings.esi_base_url}/universe/systems/{SYSTEM_ID}").mock(
        return_value=Response(200, json={"security_status": 0.9459991455078125})
    )

    resolved = await locations.resolve_location_info(db, None, settings, "token", {STATION_ID})

    info = resolved[STATION_ID]
    assert info.name == "Jita IV - Moon 4"
    assert info.security_status == 0.9459991455078125

    location_doc = await db.location_names.find_one({"_id": STATION_ID})
    assert location_doc is not None
    assert location_doc["name"] == "Jita IV - Moon 4"
    assert location_doc["system_id"] == SYSTEM_ID

    system_doc = await db.system_security.find_one({"_id": SYSTEM_ID})
    assert system_doc is not None
    assert system_doc["security_status"] == 0.9459991455078125


@respx.mock
async def test_resolve_location_info_shares_one_system_lookup_across_locations() -> None:
    settings = Settings()
    db = _mongo_db()
    second_station_id = 60003761
    respx.get(f"{settings.esi_base_url}/universe/stations/{STATION_ID}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4", "system_id": SYSTEM_ID})
    )
    respx.get(f"{settings.esi_base_url}/universe/stations/{second_station_id}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 1", "system_id": SYSTEM_ID})
    )
    system_route = respx.get(f"{settings.esi_base_url}/universe/systems/{SYSTEM_ID}").mock(
        return_value=Response(200, json={"security_status": 0.9459991455078125})
    )

    resolved = await locations.resolve_location_info(
        db, None, settings, "token", {STATION_ID, second_station_id}
    )

    assert resolved[STATION_ID].security_status == 0.9459991455078125
    assert resolved[second_station_id].security_status == 0.9459991455078125
    # Both stations sit in the same system - the system lookup must only happen once.
    assert system_route.call_count == 1


@respx.mock
async def test_resolve_location_info_uses_cached_mongo_docs_without_calling_esi() -> None:
    settings = Settings()
    db = _mongo_db()
    await db.location_names.insert_one(
        {"_id": STATION_ID, "name": "Jita IV - Moon 4", "system_id": SYSTEM_ID}
    )
    await db.system_security.insert_one({"_id": SYSTEM_ID, "security_status": 0.9459991455078125})

    resolved = await locations.resolve_location_info(db, None, settings, "token", {STATION_ID})

    assert resolved[STATION_ID].name == "Jita IV - Moon 4"
    assert resolved[STATION_ID].security_status == 0.9459991455078125


@respx.mock
async def test_resolve_location_info_handles_missing_system_id_gracefully() -> None:
    settings = Settings()
    db = _mongo_db()
    respx.get(f"{settings.esi_base_url}/universe/stations/{STATION_ID}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4"})
    )

    resolved = await locations.resolve_location_info(db, None, settings, "token", {STATION_ID})

    assert resolved[STATION_ID].name == "Jita IV - Moon 4"
    assert resolved[STATION_ID].security_status is None
