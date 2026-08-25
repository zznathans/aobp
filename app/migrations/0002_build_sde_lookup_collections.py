from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0002_build_sde_lookup_collections"

_MANUFACTURING_ACTIVITY_ID = 1
_BATCH_SIZE = 5000


async def _replace_all(
    collection: AsyncIOMotorCollection[dict[str, Any]], documents: list[dict[str, Any]]
) -> None:
    await collection.delete_many({})
    for start in range(0, len(documents), _BATCH_SIZE):
        batch = documents[start : start + _BATCH_SIZE]
        if batch:
            await collection.insert_many(batch, ordered=False)


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    type_docs = []
    async for row in db["invTypes"].find(
        {}, {"typeID": 1, "typeName": 1, "groupID": 1, "published": 1, "techLevel": 1}
    ):
        type_docs.append(
            {
                "_id": row["typeID"],
                "name": row["typeName"],
                "group_id": row["groupID"],
                "published": bool(row["published"]),
                "tech_level": row.get("techLevel"),
            }
        )

    times: dict[int, int] = {}
    async for row in db["industryActivity"].find(
        {"activityID": _MANUFACTURING_ACTIVITY_ID}, {"typeID": 1, "time": 1}
    ):
        times[row["typeID"]] = row["time"]

    materials: dict[int, list[dict[str, int]]] = {}
    async for row in db["industryActivityMaterials"].find(
        {"activityID": _MANUFACTURING_ACTIVITY_ID},
        {"typeID": 1, "materialTypeID": 1, "quantity": 1},
    ):
        materials.setdefault(row["typeID"], []).append(
            {"type_id": row["materialTypeID"], "quantity": row["quantity"]}
        )

    blueprint_docs = []
    async for row in db["industryActivityProducts"].find(
        {"activityID": _MANUFACTURING_ACTIVITY_ID},
        {"typeID": 1, "productTypeID": 1, "quantity": 1},
    ):
        blueprint_type_id = row["typeID"]
        blueprint_docs.append(
            {
                "_id": blueprint_type_id,
                "product_type_id": row["productTypeID"],
                "product_quantity": row["quantity"],
                "manufacturing_time_seconds": times.get(blueprint_type_id),
                "materials": materials.get(blueprint_type_id, []),
            }
        )

    await _replace_all(db["sde_types"], type_docs)
    await _replace_all(db["sde_blueprints"], blueprint_docs)
