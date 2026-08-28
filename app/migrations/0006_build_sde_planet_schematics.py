import gzip
import json
from pathlib import Path
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
    data_dir = Path(settings.sde_data_dir)

    with gzip.open(data_dir / "planetSchematicsTypeMap.json.gz", "rt", encoding="utf-8") as fh:
        type_map_rows: list[dict[str, Any]] = json.load(fh)

    inputs: dict[int, list[dict[str, int]]] = {}
    outputs: dict[int, dict[str, int]] = {}
    for row in type_map_rows:
        schematic_id = row["schematicID"]
        entry = {"type_id": row["typeID"], "quantity": row["quantity"]}
        if row["isInput"]:
            inputs.setdefault(schematic_id, []).append(entry)
        else:
            outputs[schematic_id] = entry

    with gzip.open(data_dir / "planetSchematics.json.gz", "rt", encoding="utf-8") as fh:
        schematic_rows: list[dict[str, Any]] = json.load(fh)

    schematic_docs = []
    for row in schematic_rows:
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
