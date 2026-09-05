from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.services.build_chain import resolve_build_chain

TRITANIUM_TYPE_ID = 34
PYERITE_TYPE_ID = 35
COMPONENT_TYPE_ID = 500
COMPONENT_BLUEPRINT_TYPE_ID = 501
SHIP_TYPE_ID = 600
SHIP_BLUEPRINT_TYPE_ID = 601
MODULE_TYPE_ID = 700
MODULE_BLUEPRINT_TYPE_ID = 701


async def _seed_names(mongo_db: AsyncMongoMockClient, docs: list[dict[str, object]]) -> None:
    await mongo_db.sde_types.insert_many(docs)


async def test_resolve_build_chain_single_level_has_no_sub_steps(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
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

    resolution = await resolve_build_chain(mongo_db, None, test_settings, SHIP_TYPE_ID, 1)

    assert resolution.is_buildable is True
    assert len(resolution.steps) == 1
    assert resolution.steps[0].type_id == SHIP_TYPE_ID
    assert resolution.steps[0].runs == 1
    assert len(resolution.raw_materials) == 1
    assert resolution.raw_materials[0].type_id == TRITANIUM_TYPE_ID
    assert resolution.raw_materials[0].quantity == 100


async def test_resolve_build_chain_expands_buildable_sub_components(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": COMPONENT_TYPE_ID, "name": "Test Component", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
            {"_id": PYERITE_TYPE_ID, "name": "Pyerite", "published": True},
        ],
    )
    await mongo_db.sde_blueprints.insert_many(
        [
            {
                "_id": SHIP_BLUEPRINT_TYPE_ID,
                "product_type_id": SHIP_TYPE_ID,
                "product_quantity": 1,
                "materials": [{"type_id": COMPONENT_TYPE_ID, "quantity": 2}],
                "activity_id": 1,
            },
            {
                "_id": COMPONENT_BLUEPRINT_TYPE_ID,
                "product_type_id": COMPONENT_TYPE_ID,
                "product_quantity": 1,
                "materials": [
                    {"type_id": TRITANIUM_TYPE_ID, "quantity": 10},
                    {"type_id": PYERITE_TYPE_ID, "quantity": 5},
                ],
                "activity_id": 1,
            },
        ]
    )

    resolution = await resolve_build_chain(
        mongo_db, None, test_settings, SHIP_TYPE_ID, 1, frozenset({COMPONENT_TYPE_ID})
    )

    assert resolution.is_buildable is True
    # Ship + Component = 2 build steps; the component is listed before the ship that needs it.
    assert [step.type_id for step in resolution.steps] == [COMPONENT_TYPE_ID, SHIP_TYPE_ID]

    component_step = resolution.steps[0]
    # Ship needs 2 components, 1 component/run -> 2 runs of the component blueprint.
    assert component_step.runs == 2

    raw_by_type_id = {material.type_id: material.quantity for material in resolution.raw_materials}
    # 2 component runs * 10 Tritanium/run = 20; * 5 Pyerite/run = 10.
    assert raw_by_type_id[TRITANIUM_TYPE_ID] == 20
    assert raw_by_type_id[PYERITE_TYPE_ID] == 10


async def test_resolve_build_chain_defaults_to_collapsed_first_level(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": COMPONENT_TYPE_ID, "name": "Test Component", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
    )
    await mongo_db.sde_blueprints.insert_many(
        [
            {
                "_id": SHIP_BLUEPRINT_TYPE_ID,
                "product_type_id": SHIP_TYPE_ID,
                "product_quantity": 1,
                "materials": [{"type_id": COMPONENT_TYPE_ID, "quantity": 2}],
                "activity_id": 1,
            },
            {
                "_id": COMPONENT_BLUEPRINT_TYPE_ID,
                "product_type_id": COMPONENT_TYPE_ID,
                "product_quantity": 1,
                "materials": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 10}],
                "activity_id": 1,
            },
        ]
    )

    # No build_set passed -> only the ship itself is expanded; the buildable component is
    # left as a leaf the caller can still choose to toggle to "build".
    resolution = await resolve_build_chain(mongo_db, None, test_settings, SHIP_TYPE_ID, 1)

    assert [step.type_id for step in resolution.steps] == [SHIP_TYPE_ID]
    assert len(resolution.raw_materials) == 1
    component_material = resolution.raw_materials[0]
    assert component_material.type_id == COMPONENT_TYPE_ID
    assert component_material.quantity == 2
    assert component_material.is_buildable is True


async def test_resolve_build_chain_marks_non_buildable_leaf(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
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

    resolution = await resolve_build_chain(mongo_db, None, test_settings, SHIP_TYPE_ID, 1)

    assert resolution.raw_materials[0].is_buildable is False


async def test_resolve_build_chain_merges_shared_component_across_branches(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": MODULE_TYPE_ID, "name": "Test Module", "published": True},
            {"_id": COMPONENT_TYPE_ID, "name": "Shared Component", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
    )
    await mongo_db.sde_blueprints.insert_many(
        [
            {
                "_id": SHIP_BLUEPRINT_TYPE_ID,
                "product_type_id": SHIP_TYPE_ID,
                "product_quantity": 1,
                # Ship needs both the module and the shared component directly.
                "materials": [
                    {"type_id": MODULE_TYPE_ID, "quantity": 1},
                    {"type_id": COMPONENT_TYPE_ID, "quantity": 1},
                ],
                "activity_id": 1,
            },
            {
                "_id": MODULE_BLUEPRINT_TYPE_ID,
                "product_type_id": MODULE_TYPE_ID,
                "product_quantity": 1,
                # The module *also* needs the shared component.
                "materials": [{"type_id": COMPONENT_TYPE_ID, "quantity": 1}],
                "activity_id": 1,
            },
            {
                "_id": COMPONENT_BLUEPRINT_TYPE_ID,
                "product_type_id": COMPONENT_TYPE_ID,
                "product_quantity": 1,
                "materials": [{"type_id": TRITANIUM_TYPE_ID, "quantity": 10}],
                "activity_id": 1,
            },
        ]
    )

    resolution = await resolve_build_chain(
        mongo_db,
        None,
        test_settings,
        SHIP_TYPE_ID,
        1,
        frozenset({MODULE_TYPE_ID, COMPONENT_TYPE_ID}),
    )

    # Shared component appears as exactly one step, not two.
    component_steps = [step for step in resolution.steps if step.type_id == COMPONENT_TYPE_ID]
    assert len(component_steps) == 1
    # Demanded once directly by the ship and once via the module -> 2 runs total.
    assert component_steps[0].runs == 2

    raw_by_type_id = {material.type_id: material.quantity for material in resolution.raw_materials}
    assert raw_by_type_id[TRITANIUM_TYPE_ID] == 20


async def test_resolve_build_chain_scales_with_target_quantity(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
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

    resolution = await resolve_build_chain(mongo_db, None, test_settings, SHIP_TYPE_ID, 3)

    assert resolution.steps[0].runs == 3
    assert resolution.raw_materials[0].quantity == 300


async def test_resolve_build_chain_marks_unbuildable_item(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db, [{"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True}]
    )

    resolution = await resolve_build_chain(mongo_db, None, test_settings, TRITANIUM_TYPE_ID, 1)

    assert resolution.is_buildable is False
    assert resolution.steps == []
    # The target itself has nowhere to go but "raw" - it's the one thing you'd have to buy.
    assert [m.type_id for m in resolution.raw_materials] == [TRITANIUM_TYPE_ID]


async def test_resolve_build_chain_computes_costs_from_market_prices(
    mongo_db: AsyncMongoMockClient, test_settings: Settings
) -> None:
    await _seed_names(
        mongo_db,
        [
            {"_id": SHIP_TYPE_ID, "name": "Test Ship", "published": True},
            {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "published": True},
        ],
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
    await mongo_db.market_prices.insert_many(
        [
            {"_id": TRITANIUM_TYPE_ID, "adjusted_price": 5.0, "average_price": 5.0},
            {"_id": SHIP_TYPE_ID, "adjusted_price": 1000.0, "average_price": 1000.0},
        ]
    )

    resolution = await resolve_build_chain(mongo_db, None, test_settings, SHIP_TYPE_ID, 1)

    assert resolution.raw_material_cost == 500.0
    assert resolution.output_value == 1000.0
