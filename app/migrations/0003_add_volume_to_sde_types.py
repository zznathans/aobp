import asyncio

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0003_add_volume_to_sde_types"

_BATCH_SIZE = 500


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    volume_by_type_id: dict[int, float] = {}
    async for row in db["invTypes"].find({}, {"typeID": 1, "volume": 1}):
        volume_by_type_id[row["typeID"]] = row.get("volume") or 0.0

    entries = list(volume_by_type_id.items())
    for start in range(0, len(entries), _BATCH_SIZE):
        batch = entries[start : start + _BATCH_SIZE]
        await asyncio.gather(
            *(
                db["sde_types"].update_one({"_id": type_id}, {"$set": {"volume": volume}})
                for type_id, volume in batch
            )
        )
