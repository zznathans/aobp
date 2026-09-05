import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.web import format_isk
from tests.test_blueprints_routes import CHARACTER_ID, _log_in, _mock_assets

RIFTER_BLUEPRINT_TYPE_ID = 588
RIFTER_PRODUCT_TYPE_ID = 587
PUNISHER_BLUEPRINT_TYPE_ID = 598
PUNISHER_PRODUCT_TYPE_ID = 597
TRITANIUM_TYPE_ID = 34


async def _seed_two_blueprints_sharing_tritanium(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.sde_types.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
            {"_id": RIFTER_PRODUCT_TYPE_ID, "name": "Rifter", "published": True},
            {
                "_id": RIFTER_BLUEPRINT_TYPE_ID,
                "name": "Rifter Blueprint",
                "published": True,
                "tech_level": None,
            },
            {"_id": PUNISHER_PRODUCT_TYPE_ID, "name": "Punisher", "published": True},
            {
                "_id": PUNISHER_BLUEPRINT_TYPE_ID,
                "name": "Punisher Blueprint",
                "published": True,
                "tech_level": None,
            },
        ]
    )
    await mongo_db.sde_blueprints.insert_many(
        [
            {
                "_id": RIFTER_BLUEPRINT_TYPE_ID,
                "product_type_id": RIFTER_PRODUCT_TYPE_ID,
                "product_quantity": 1,
                "manufacturing_time_seconds": 1200,
                "materials": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 100}],
                "activity_id": 1,
            },
            {
                "_id": PUNISHER_BLUEPRINT_TYPE_ID,
                "product_type_id": PUNISHER_PRODUCT_TYPE_ID,
                "product_quantity": 1,
                "manufacturing_time_seconds": 1200,
                "materials": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 50}],
                "activity_id": 1,
            },
        ]
    )


def _create_plan(client: TestClient, *, name: str = "My Plan") -> str:
    response = client.post(
        "/plans",
        data={
            "name": name,
            f"include__c{RIFTER_BLUEPRINT_TYPE_ID}": "1",
            f"type_id__c{RIFTER_BLUEPRINT_TYPE_ID}": str(RIFTER_BLUEPRINT_TYPE_ID),
            f"runs__c{RIFTER_BLUEPRINT_TYPE_ID}": "2",
            f"me__c{RIFTER_BLUEPRINT_TYPE_ID}": "0",
            f"source_item_id__c{RIFTER_BLUEPRINT_TYPE_ID}": "",
            f"location_id__c{RIFTER_BLUEPRINT_TYPE_ID}": "",
            f"include__c{PUNISHER_BLUEPRINT_TYPE_ID}": "1",
            f"type_id__c{PUNISHER_BLUEPRINT_TYPE_ID}": str(PUNISHER_BLUEPRINT_TYPE_ID),
            f"runs__c{PUNISHER_BLUEPRINT_TYPE_ID}": "1",
            f"me__c{PUNISHER_BLUEPRINT_TYPE_ID}": "0",
            f"source_item_id__c{PUNISHER_BLUEPRINT_TYPE_ID}": "",
            f"location_id__c{PUNISHER_BLUEPRINT_TYPE_ID}": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].rsplit("/", 1)[-1]


@respx.mock
async def test_create_plan_aggregates_materials_across_blueprints(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=120)

    plan_id = _create_plan(client)
    response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200
    assert "Rifter Blueprint" in response.text
    assert "Punisher Blueprint" in response.text
    # Rifter needs 100/run * 2 runs = 200; Punisher needs 50/run * 1 run = 50 -> 250 total.
    assert item_line_value(response.text, "Needed") == "250"
    assert item_line_value(response.text, "Have") == "120"
    # 250 needed - 120 have = 130 missing.
    assert "130" in response.text


def item_line_value(html: str, label: str) -> str:
    marker = f"<span>{label}</span>"
    index = html.index(marker)
    value_start = html.index('class="item-value">', index) + len('class="item-value">')
    value_end = html.index("</span>", value_start)
    return html[value_start:value_end].strip()


@respx.mock
async def test_plan_totals_equal_sum_of_per_line_costs(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)
    await mongo_db.market_prices.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "adjusted_price": 5.0, "average_price": 5.0},
            {"_id": RIFTER_PRODUCT_TYPE_ID, "adjusted_price": 1000.0, "average_price": 1000.0},
            {"_id": PUNISHER_PRODUCT_TYPE_ID, "adjusted_price": 800.0, "average_price": 800.0},
        ]
    )

    plan_id = _create_plan(client)
    response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200
    # Rifter: 100 Tritanium/run * 5 ISK * 2 runs = 1000 ISK cost, output 1000*2 = 2000 ISK.
    # Punisher: 50 * 5 * 1 = 250 ISK cost, output 800 ISK.
    # Totals: cost 1250, output 2800, profit 1550.
    assert f'<div class="value">{format_isk(1250)}</div>' in response.text
    assert f'<div class="value">{format_isk(2800)}</div>' in response.text
    assert f'<div class="value">{format_isk(1550)}</div>' in response.text


@respx.mock
async def test_update_line_changes_runs_and_recomputes(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)

    plan_id = _create_plan(client)
    doc = await mongo_db.plans.find_one({"_id": plan_id})
    rifter_line_id = next(
        line["line_id"] for line in doc["lines"] if line["type_id"] == RIFTER_BLUEPRINT_TYPE_ID
    )

    response = client.post(
        f"/plans/{plan_id}/lines/{rifter_line_id}",
        data={"runs": "5", "material_efficiency": "10"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    updated_doc = await mongo_db.plans.find_one({"_id": plan_id})
    updated_line = next(line for line in updated_doc["lines"] if line["line_id"] == rifter_line_id)
    assert updated_line["runs"] == 5
    assert updated_line["material_efficiency"] == 10


@respx.mock
async def test_remove_line_deletes_it_from_plan(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)

    plan_id = _create_plan(client)
    doc = await mongo_db.plans.find_one({"_id": plan_id})
    rifter_line_id = next(
        line["line_id"] for line in doc["lines"] if line["type_id"] == RIFTER_BLUEPRINT_TYPE_ID
    )

    response = client.post(
        f"/plans/{plan_id}/lines/{rifter_line_id}/delete", follow_redirects=False
    )
    assert response.status_code == 303

    updated_doc = await mongo_db.plans.find_one({"_id": plan_id})
    assert len(updated_doc["lines"]) == 1
    assert updated_doc["lines"][0]["type_id"] == PUNISHER_BLUEPRINT_TYPE_ID


@respx.mock
async def test_delete_plan_removes_it(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)

    plan_id = _create_plan(client)
    response = client.post(f"/plans/{plan_id}/delete", follow_redirects=False)
    assert response.status_code == 303

    follow_up = client.get(f"/plans/{plan_id}")
    assert follow_up.status_code == 404


@respx.mock
async def test_plan_is_scoped_to_owning_character(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)
    plan_id = _create_plan(client)

    # Insert a second character's plan document directly and confirm the first
    # character can't see or delete it.
    await mongo_db.plans.update_one({"_id": plan_id}, {"$set": {"character_id": CHARACTER_ID + 1}})

    response = client.get(f"/plans/{plan_id}")
    assert response.status_code == 404

    delete_response = client.post(f"/plans/{plan_id}/delete", follow_redirects=False)
    assert delete_response.status_code == 404


@respx.mock
async def test_plans_list_shows_saved_plans(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_two_blueprints_sharing_tritanium(mongo_db)
    _mock_assets(test_settings, on_site=0, elsewhere=0)
    _create_plan(client, name="Ship Run")

    response = client.get("/plans")

    assert response.status_code == 200
    assert "Ship Run" in response.text
