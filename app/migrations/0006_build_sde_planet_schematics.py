from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0006_build_sde_planet_schematics"

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
    inputs: dict[int, list[dict[str, int]]] = {}
    outputs: dict[int, dict[str, int]] = {}
    async for row in db["planetSchematicsTypeMap"].find(
        {}, {"schematicID": 1, "typeID": 1, "quantity": 1, "isInput": 1}
    ):
        schematic_id = row["schematicID"]
        entry = {"type_id": row["typeID"], "quantity": row["quantity"]}
        if row["isInput"]:
            inputs.setdefault(schematic_id, []).append(entry)
        else:
            outputs[schematic_id] = entry

    schematic_docs = []
    async for row in db["planetSchematics"].find(
        {}, {"schematicID": 1, "schematicName": 1, "cycleTime": 1}
    ):
        schematic_id = row["schematicID"]
        output = outputs.get(schematic_id)
        if output is None:
            continue
        schematic_docs.append(
            {
                "_id": schematic_id,
                "name": row["schematicName"],
                "cycle_time_seconds": row["cycleTime"],
                "output": output,
                "inputs": inputs.get(schematic_id, []),
            }
        )

    await _replace_all(db["sde_planet_schematics"], schematic_docs)
