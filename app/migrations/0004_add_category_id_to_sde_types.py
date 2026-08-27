import asyncio
import gzip
import json
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0004_add_category_id_to_sde_types"

_BATCH_SIZE = 500


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    path = Path(settings.sde_data_dir) / "invGroups.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        groups: list[dict[str, Any]] = json.load(fh)
    category_id_by_group_id = {row["groupID"]: row["categoryID"] for row in groups}

    type_docs = await db["sde_types"].find({}, {"group_id": 1}).to_list(None)
    entries = [
        (doc["_id"], category_id_by_group_id[doc["group_id"]])
        for doc in type_docs
        if doc.get("group_id") in category_id_by_group_id
    ]

    for start in range(0, len(entries), _BATCH_SIZE):
        batch = entries[start : start + _BATCH_SIZE]
        await asyncio.gather(
            *(
                db["sde_types"].update_one({"_id": type_id}, {"$set": {"category_id": category_id}})
                for type_id, category_id in batch
            )
        )
