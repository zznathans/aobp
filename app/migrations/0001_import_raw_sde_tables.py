import gzip
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0001_import_raw_sde_tables"

_BATCH_SIZE = 5000

# The SDE ships ~180 raw tables, most totaling hundreds of MB uncompressed
# (e.g. trnTranslations, mapDenormalize, mapCelestialStatistics) - only these
# are ever read downstream (by 0002_build_sde_lookup_collections), so that's
# all that gets imported.
_REQUIRED_TABLES = frozenset(
    {
        "invTypes",
        "industryActivity",
        "industryActivityMaterials",
        "industryActivityProducts",
    }
)

logger = logging.getLogger("eve-build.migrations")


def _step_id(table_name: str) -> str:
    return f"{MIGRATION_ID}:{table_name}"


async def _import_table(db: AsyncIOMotorDatabase, path: Path) -> None:
    table_name = path.name.removesuffix(".json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        rows: list[dict[str, Any]] = json.load(fh)

    collection = db[table_name]
    await collection.delete_many({})
    for start in range(0, len(rows), _BATCH_SIZE):
        batch = rows[start : start + _BATCH_SIZE]
        if batch:
            await collection.insert_many(batch, ordered=False)


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    data_dir = Path(settings.sde_data_dir)
    paths = sorted(
        path
        for path in data_dir.glob("*.json.gz")
        if path.name.removesuffix(".json.gz") in _REQUIRED_TABLES
    )

    applied_steps = {
        doc["_id"]
        async for doc in db["_migrations"].find(
            {"_id": {"$in": [_step_id(path.name.removesuffix(".json.gz")) for path in paths]}},
            {"_id": 1},
        )
    }

    for path in paths:
        table_name = path.name.removesuffix(".json.gz")
        step_id = _step_id(table_name)
        if step_id in applied_steps:
            logger.info("Skipping already-imported SDE table %s", table_name)
            continue
        logger.info("Importing SDE table %s", table_name)
        await _import_table(db, path)
        await db["_migrations"].insert_one(
            {"_id": step_id, "applied_at": datetime.now(UTC).replace(tzinfo=None)}
        )
        logger.info("Imported SDE table %s", table_name)
