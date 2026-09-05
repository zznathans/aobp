import json
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.db.index_sync import load_index_configs, sync_indexes


def _write_config(config_dir: Path, filename: str, collection: str, indexes: list[dict]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / filename).write_text(json.dumps({"collection": collection, "indexes": indexes}))


async def test_sync_creates_missing_indexes(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [{"name": "owner_id", "keys": [["owner_id", 1]]}],
    )
    db = AsyncMongoMockClient()["test"]

    await sync_indexes(db, str(tmp_path))

    index_info = await db["widgets"].index_information()
    assert "owner_id" in index_info
    record = await db["_index_config"].find_one({"_id": "widgets.owner_id"})
    assert record is not None
    assert record["spec"]["keys"] == [["owner_id", 1]]


async def test_sync_is_idempotent(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [{"name": "owner_id", "keys": [["owner_id", 1]]}],
    )
    db = AsyncMongoMockClient()["test"]

    await sync_indexes(db, str(tmp_path))
    await sync_indexes(db, str(tmp_path))

    index_info = await db["widgets"].index_information()
    assert "owner_id" in index_info
    assert await db["_index_config"].count_documents({}) == 1


async def test_sync_recreates_index_when_spec_changes(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [{"name": "owner_id", "keys": [["owner_id", 1]]}],
    )
    db = AsyncMongoMockClient()["test"]
    await sync_indexes(db, str(tmp_path))

    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [{"name": "owner_id", "keys": [["owner_id", 1]], "unique": True}],
    )
    await sync_indexes(db, str(tmp_path))

    index_info = await db["widgets"].index_information()
    assert index_info["owner_id"]["unique"] is True
    record = await db["_index_config"].find_one({"_id": "widgets.owner_id"})
    assert record is not None
    assert record["spec"]["unique"] is True


async def test_sync_drops_index_removed_from_config(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [{"name": "owner_id", "keys": [["owner_id", 1]]}],
    )
    db = AsyncMongoMockClient()["test"]
    await sync_indexes(db, str(tmp_path))

    _write_config(tmp_path, "widgets.json", "widgets", [])
    await sync_indexes(db, str(tmp_path))

    index_info = await db["widgets"].index_information()
    assert "owner_id" not in index_info
    assert await db["_index_config"].count_documents({}) == 0


async def test_sync_leaves_unmanaged_index_alone(tmp_path: Path) -> None:
    db = AsyncMongoMockClient()["test"]
    await db["widgets"].create_index([("legacy_field", 1)], name="legacy_manual_index")

    _write_config(tmp_path, "widgets.json", "widgets", [])
    await sync_indexes(db, str(tmp_path))

    index_info = await db["widgets"].index_information()
    assert "legacy_manual_index" in index_info


def test_load_index_configs_rejects_missing_name_or_keys(tmp_path: Path) -> None:
    _write_config(tmp_path, "widgets.json", "widgets", [{"keys": [["owner_id", 1]]}])

    with pytest.raises(ValueError, match="missing required 'name' or 'keys'"):
        load_index_configs(str(tmp_path))


def test_load_index_configs_rejects_duplicate_names(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "widgets.json",
        "widgets",
        [
            {"name": "owner_id", "keys": [["owner_id", 1]]},
            {"name": "owner_id", "keys": [["owner_id", -1]]},
        ],
    )

    with pytest.raises(ValueError, match="duplicate index name"):
        load_index_configs(str(tmp_path))
