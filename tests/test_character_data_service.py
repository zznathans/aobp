import respx
from fakeredis.aioredis import FakeRedis
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.services import character_data

CHARACTER_ID = 555


def _mongo_db() -> object:
    return AsyncMongoMockClient()["eve-build"]


def _asset_response_route(settings: Settings) -> respx.Route:
    url = f"{settings.esi_base_url}/characters/{CHARACTER_ID}/assets"
    return respx.get(url, params={"page": 1}).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "1"},
            json=[
                {
                    "item_id": 1,
                    "type_id": 34,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 100,
                    "is_singleton": False,
                }
            ],
        )
    )


@respx.mock
async def test_get_character_assets_persists_to_mongo() -> None:
    settings = Settings()
    db = _mongo_db()
    redis = FakeRedis()
    _asset_response_route(settings)

    assets = await character_data.get_character_assets(db, redis, settings, "token", CHARACTER_ID)

    assert len(assets) == 1
    assert assets[0].type_id == 34

    docs = await db.assets.find({"character_id": CHARACTER_ID}).to_list(None)
    assert len(docs) == 1
    assert docs[0]["type_id"] == 34
    assert docs[0]["character_id"] == CHARACTER_ID


@respx.mock
async def test_get_character_assets_second_call_uses_cache() -> None:
    settings = Settings()
    db = _mongo_db()
    redis = FakeRedis()
    route = _asset_response_route(settings)

    first = await character_data.get_character_assets(db, redis, settings, "token", CHARACTER_ID)
    second = await character_data.get_character_assets(db, redis, settings, "token", CHARACTER_ID)

    assert first == second
    assert route.call_count == 1
