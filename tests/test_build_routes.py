from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

SHIP_TYPE_ID = 600
SHIP_BLUEPRINT_TYPE_ID = 601
TRITANIUM_TYPE_ID = 34


async def _seed_buildable_ship(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.sde_types.insert_many(
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ]
    )
    await mongo_db.sde_blueprints.insert_one(
        {
            "_id": SHIP_BLUEPRINT_TYPE_ID,
            "product_type_id": SHIP_TYPE_ID,
            "product_quantity": 1,
            "materials": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 100}],
            "activity_id": 1,
        }
    )


def test_build_chooser_shows_both_options(client: TestClient) -> None:
    response = client.get("/build")

    assert response.status_code == 200
    assert "I know what I want to build" in response.text
    assert 'href="/build/items"' in response.text
    assert "I know which blueprint I want" in response.text
    assert 'href="/blueprints/catalog"' in response.text


async def test_item_search_finds_items_by_name(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await _seed_buildable_ship(mongo_db)

    response = client.get("/build/items", params={"q": "test ship"})

    assert response.status_code == 200
    assert "Test Ship" in response.text
    assert f'href="/build/items/{SHIP_TYPE_ID}"' in response.text


async def test_item_search_prompts_for_more_characters(client: TestClient) -> None:
    response = client.get("/build/items", params={"q": "a"})

    assert response.status_code == 200
    assert "Keep typing" in response.text


async def test_item_build_chain_shows_raw_materials(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await _seed_buildable_ship(mongo_db)

    response = client.get(f"/build/items/{SHIP_TYPE_ID}")

    assert response.status_code == 200
    assert "Test Ship" in response.text
    assert "Tritanium" in response.text
    assert '<span class="item-value">100</span>' in response.text
    assert '<div class="value">1</div>' in response.text  # 1 build step


async def test_item_build_chain_scales_by_quantity(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await _seed_buildable_ship(mongo_db)

    response = client.get(f"/build/items/{SHIP_TYPE_ID}", params={"qty": 3})

    assert response.status_code == 200
    assert "Building 3" in response.text
    assert '<span class="item-value">300</span>' in response.text


async def test_item_build_chain_404s_for_unknown_item(client: TestClient) -> None:
    response = client.get("/build/items/999999999")

    assert response.status_code == 404


async def test_item_build_chain_shows_not_buildable_message(
    client: TestClient, mongo_db: AsyncMongoMockClient
) -> None:
    await mongo_db.sde_types.insert_one(
        {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True}
    )

    response = client.get(f"/build/items/{TRITANIUM_TYPE_ID}")

    assert response.status_code == 200
    assert "can only" in response.text
    assert "be bought, not built" in response.text
