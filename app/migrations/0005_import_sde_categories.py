import gzip
import json
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0005_import_sde_categories"

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
    path = Path(settings.sde_data_dir) / "invCategories.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        categories: list[dict[str, Any]] = json.load(fh)

    category_docs = [{"_id": row["categoryID"], "name": row["categoryName"]} for row in categories]
    await _replace_all(db["sde_categories"], category_docs)
