import gzip
import json
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0001_import_raw_sde_tables"

_BATCH_SIZE = 5000


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    data_dir = Path(settings.sde_data_dir)

    for path in sorted(data_dir.glob("*.json.gz")):
        table_name = path.name.removesuffix(".json.gz")
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows: list[dict[str, Any]] = json.load(fh)

        collection = db[table_name]
        await collection.delete_many({})
        for start in range(0, len(rows), _BATCH_SIZE):
            batch = rows[start : start + _BATCH_SIZE]
            if batch:
                await collection.insert_many(batch, ordered=False)
