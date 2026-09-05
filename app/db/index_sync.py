import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

logger = logging.getLogger("eve-build.index_sync")

_ALLOWED_OPTIONS = {"unique", "sparse", "expireAfterSeconds"}


def load_index_configs(indexes_dir: str) -> dict[str, list[dict[str, Any]]]:
    configs: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(Path(indexes_dir).glob("*.json")):
        data = json.loads(path.read_text())
        collection = data["collection"]
        indexes = data["indexes"]

        seen_names: set[str] = set()
        for spec in indexes:
            name = spec.get("name")
            keys = spec.get("keys")
            if not name or not keys:
                raise ValueError(
                    f"{path}: index spec for collection {collection!r} is missing "
                    "required 'name' or 'keys'"
                )
            if name in seen_names:
                raise ValueError(
                    f"{path}: duplicate index name {name!r} for collection {collection!r}"
                )
            seen_names.add(name)

        configs.setdefault(collection, []).extend(indexes)
    return configs


def _index_options(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: spec[key] for key in _ALLOWED_OPTIONS if key in spec}


async def _drop_index_if_exists(db: AsyncIOMotorDatabase, collection: str, name: str) -> None:
    with contextlib.suppress(OperationFailure):
        await db[collection].drop_index(name)


async def sync_indexes(db: AsyncIOMotorDatabase, indexes_dir: str) -> None:
    desired = load_index_configs(indexes_dir)

    desired_ids: set[str] = set()
    for collection, specs in desired.items():
        for spec in specs:
            name = spec["name"]
            record_id = f"{collection}.{name}"
            desired_ids.add(record_id)

            existing_record = await db["_index_config"].find_one({"_id": record_id})
            if existing_record is not None and existing_record["spec"] == spec:
                continue

            logger.info("Syncing index %s on collection %s", name, collection)
            await _drop_index_if_exists(db, collection, name)
            keys = [tuple(pair) for pair in spec["keys"]]
            await db[collection].create_index(keys, name=name, **_index_options(spec))
            await db["_index_config"].replace_one(
                {"_id": record_id},
                {"_id": record_id, "collection": collection, "name": name, "spec": spec},
                upsert=True,
            )

    async for record in db["_index_config"].find({}):
        if record["_id"] in desired_ids:
            continue
        logger.info(
            "Dropping unmanaged index %s on collection %s (no longer in config)",
            record["name"],
            record["collection"],
        )
        await _drop_index_if_exists(db, record["collection"], record["name"])
        await db["_index_config"].delete_one({"_id": record["_id"]})
