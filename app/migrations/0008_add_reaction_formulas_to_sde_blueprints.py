import asyncio

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0008_add_reaction_formulas_to_sde_blueprints"

_MANUFACTURING_ACTIVITY_ID = 1
_REACTIONS_ACTIVITY_ID = 11
_BATCH_SIZE = 500


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    times: dict[int, int] = {}
    async for row in db["industryActivity"].find(
        {"activityID": _REACTIONS_ACTIVITY_ID}, {"typeID": 1, "time": 1}
    ):
        times[row["typeID"]] = row["time"]

    materials: dict[int, list[dict[str, int]]] = {}
    async for row in db["industryActivityMaterials"].find(
        {"activityID": _REACTIONS_ACTIVITY_ID},
        {"typeID": 1, "materialTypeID": 1, "quantity": 1},
    ):
        materials.setdefault(row["typeID"], []).append(
            {"type_id": row["materialTypeID"], "quantity": row["quantity"]}
        )

    reaction_docs = []
    async for row in db["industryActivityProducts"].find(
        {"activityID": _REACTIONS_ACTIVITY_ID},
        {"typeID": 1, "productTypeID": 1, "quantity": 1},
    ):
        reaction_type_id = row["typeID"]
        reaction_docs.append(
            {
                "_id": reaction_type_id,
                "product_type_id": row["productTypeID"],
                "product_quantity": row["quantity"],
                "manufacturing_time_seconds": times.get(reaction_type_id),
                "materials": materials.get(reaction_type_id, []),
                "activity_id": _REACTIONS_ACTIVITY_ID,
            }
        )

    for start in range(0, len(reaction_docs), _BATCH_SIZE):
        batch = reaction_docs[start : start + _BATCH_SIZE]
        await asyncio.gather(
            *(
                db["sde_blueprints"].update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
                for doc in batch
            )
        )

    await db["sde_blueprints"].update_many(
        {"activity_id": {"$exists": False}}, {"$set": {"activity_id": _MANUFACTURING_ACTIVITY_ID}}
    )
