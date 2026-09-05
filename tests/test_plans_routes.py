import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from tests.test_blueprints_routes import CHARACTER_ID, _log_in
from tests.test_build_routes import (
    COMPONENT_TYPE_ID,
    SHIP_TYPE_ID,
    _seed_buildable_ship,
    _seed_two_level_ship,
)


@respx.mock
async def test_plans_create_requires_login(client: TestClient) -> None:
    response = client.get("/plans/create", params={"type_id": SHIP_TYPE_ID})

    assert response.status_code == 401


@respx.mock
async def test_plans_create_saves_and_redirects(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_level_ship(mongo_db)

    response = client.get(
        "/plans/create",
        params={"type_id": SHIP_TYPE_ID, "qty": 2, "build": str(COMPONENT_TYPE_ID)},
        follow_redirects=False,
    )

    assert response.status_code in (302, 303, 307)
    location = response.headers["location"]
    assert location.startswith("/plans/")
    plan_id = location.removeprefix("/plans/")

    doc = await mongo_db.plans.find_one({"_id": plan_id})
    assert doc is not None
    assert doc["character_id"] == CHARACTER_ID
    assert doc["target_type_id"] == SHIP_TYPE_ID
    assert doc["target_quantity"] == 2
    assert doc["build_set"] == [COMPONENT_TYPE_ID]


@respx.mock
async def test_plan_detail_renders_resolved_chain_read_only(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_level_ship(mongo_db)

    create_response = client.get(
        "/plans/create",
        params={"type_id": SHIP_TYPE_ID, "qty": 1, "build": str(COMPONENT_TYPE_ID)},
        follow_redirects=False,
    )
    plan_id = create_response.headers["location"].removeprefix("/plans/")

    response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200
    assert "Test Ship" in response.text
    assert "Test Component" in response.text
    assert "Tritanium" in response.text
    # Component was toggled to "build" when the plan was saved, so it's an expanded step
    # (collapse-to-buy flag) with Tritanium as its own bought-leaf material.
    assert '<span class="flag flag-buy-toggle">Buy</span>' in response.text
    assert '<span class="flag flag-buy">Bought</span>' in response.text
    # Read-only: no clickable Build/Buy toggle links, just plain flag spans.
    assert '<a class="flag flag-build"' not in response.text
    assert '<a class="flag flag-buy-toggle"' not in response.text
    assert '<a class="flag flag-buy" ' not in response.text


@respx.mock
async def test_plan_detail_renders_unexpanded_buildable_material_as_a_span(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_level_ship(mongo_db)

    create_response = client.get(
        "/plans/create", params={"type_id": SHIP_TYPE_ID, "qty": 1}, follow_redirects=False
    )
    plan_id = create_response.headers["location"].removeprefix("/plans/")

    response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200
    # Component wasn't toggled to "build" when saved, so it's a buildable-but-uncollapsed
    # leaf material - a plain "Build" flag span, not a clickable toggle link.
    assert '<span class="flag flag-build">Build</span>' in response.text
    assert '<a class="flag flag-build"' not in response.text


@respx.mock
async def test_plan_detail_404s_for_unknown_id(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/plans/nonexistent")

    assert response.status_code == 404


@respx.mock
async def test_plan_detail_404s_for_a_different_owners_plan(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    await _seed_buildable_ship(mongo_db)
    await mongo_db.plans.insert_one(
        {
            "_id": "someone-elses-plan",
            "character_id": CHARACTER_ID + 1,
            "target_type_id": SHIP_TYPE_ID,
            "target_quantity": 1,
            "build_set": [],
            "created_at": None,
            "updated_at": None,
        }
    )
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/plans/someone-elses-plan")

    assert response.status_code == 404


@respx.mock
async def test_plans_list_requires_login(client: TestClient) -> None:
    response = client.get("/plans")

    assert response.status_code == 401


@respx.mock
async def test_plans_list_shows_empty_message(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/plans")

    assert response.status_code == 200
    assert "No plans saved yet" in response.text


@respx.mock
async def test_plans_list_shows_saved_plans_with_links(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_buildable_ship(mongo_db)

    create_response = client.get(
        "/plans/create", params={"type_id": SHIP_TYPE_ID, "qty": 5}, follow_redirects=False
    )
    plan_id = create_response.headers["location"].removeprefix("/plans/")

    response = client.get("/plans")

    assert response.status_code == 200
    assert "Test Ship" in response.text
    assert f'href="/plans/{plan_id}"' in response.text
