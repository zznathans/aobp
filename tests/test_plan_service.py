from datetime import datetime

from mongomock_motor import AsyncMongoMockClient

from app.services.plan import create_plan, get_plan, list_plans

CHARACTER_ID = 555
OTHER_CHARACTER_ID = 556
SHIP_TYPE_ID = 600


async def test_create_plan_inserts_expected_fields(mongo_db: AsyncMongoMockClient) -> None:
    plan_id = await create_plan(mongo_db, CHARACTER_ID, SHIP_TYPE_ID, 3, frozenset({57478, 57479}))

    doc = await mongo_db.plans.find_one({"_id": plan_id})
    assert doc is not None
    assert doc["character_id"] == CHARACTER_ID
    assert doc["target_type_id"] == SHIP_TYPE_ID
    assert doc["target_quantity"] == 3
    assert doc["build_set"] == [57478, 57479]
    assert doc["created_at"] is not None
    assert doc["updated_at"] == doc["created_at"]


async def test_get_plan_returns_none_for_unknown_id(mongo_db: AsyncMongoMockClient) -> None:
    assert await get_plan(mongo_db, "nonexistent", CHARACTER_ID) is None


async def test_get_plan_returns_none_for_a_different_owner(
    mongo_db: AsyncMongoMockClient,
) -> None:
    plan_id = await create_plan(mongo_db, CHARACTER_ID, SHIP_TYPE_ID, 1, frozenset())

    assert await get_plan(mongo_db, plan_id, OTHER_CHARACTER_ID) is None
    assert await get_plan(mongo_db, plan_id, CHARACTER_ID) is not None


async def test_list_plans_scopes_to_character_and_sorts_by_recency(
    mongo_db: AsyncMongoMockClient,
) -> None:
    first_id = await create_plan(mongo_db, CHARACTER_ID, SHIP_TYPE_ID, 1, frozenset())
    second_id = await create_plan(mongo_db, CHARACTER_ID, SHIP_TYPE_ID, 2, frozenset())
    await create_plan(mongo_db, OTHER_CHARACTER_ID, SHIP_TYPE_ID, 1, frozenset())
    # Bump the first plan's updated_at so it should now sort ahead of the second.
    await mongo_db.plans.update_one(
        {"_id": first_id}, {"$set": {"updated_at": datetime(2999, 1, 1)}}
    )

    plans = await list_plans(mongo_db, CHARACTER_ID)

    assert [doc["_id"] for doc in plans] == [first_id, second_id]
