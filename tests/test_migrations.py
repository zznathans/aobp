import gzip
import importlib
import json
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.migrations.runner import run_migrations

_TABLE_FIXTURES: dict[str, list[dict[str, object]]] = {
    "invTypes": [
        {"typeID": 34, "typeName": "Tritanium", "groupID": 18, "published": 1, "techLevel": None},
        {"typeID": 587, "typeName": "Rifter", "groupID": 25, "published": 1, "techLevel": 1},
        {
            "typeID": 588,
            "typeName": "Rifter Blueprint",
            "groupID": 25,
            "published": 1,
            "techLevel": None,
        },
    ],
    "industryActivity": [{"typeID": 588, "activityID": 1, "time": 1200}],
    "industryActivityMaterials": [
        {"typeID": 588, "activityID": 1, "materialTypeID": 34, "quantity": 4500}
    ],
    "industryActivityProducts": [
        {"typeID": 588, "activityID": 1, "productTypeID": 587, "quantity": 1}
    ],
}


def _write_fixtures(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for table_name, rows in _TABLE_FIXTURES.items():
        with gzip.open(data_dir / f"{table_name}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(rows, fh)


def _settings(data_dir: Path) -> Settings:
    return Settings(sde_data_dir=str(data_dir))


async def test_run_migrations_populates_raw_and_lookup_collections(tmp_path: Path) -> None:
    _write_fixtures(tmp_path)
    db = AsyncMongoMockClient()["test"]

    await run_migrations(db, _settings(tmp_path))

    applied_ids = {doc["_id"] async for doc in db["_migrations"].find({}, {"_id": 1})}
    assert applied_ids == {
        "0001_import_raw_sde_tables",
        "0002_build_sde_lookup_collections",
    }

    assert await db["invTypes"].count_documents({}) == 3
    assert await db["sde_types"].count_documents({}) == 3
    assert await db["sde_blueprints"].count_documents({}) == 1

    rifter_blueprint = await db["sde_blueprints"].find_one({"_id": 588})
    assert rifter_blueprint == {
        "_id": 588,
        "product_type_id": 587,
        "product_quantity": 1,
        "manufacturing_time_seconds": 1200,
        "materials": [{"type_id": 34, "quantity": 4500}],
    }


async def test_run_migrations_is_idempotent(tmp_path: Path) -> None:
    _write_fixtures(tmp_path)
    db = AsyncMongoMockClient()["test"]
    settings = _settings(tmp_path)

    await run_migrations(db, settings)
    await run_migrations(db, settings)

    assert await db["_migrations"].count_documents({}) == 2
    assert await db["sde_blueprints"].count_documents({}) == 1


async def test_failed_migration_is_not_recorded_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_fixtures(tmp_path)
    db = AsyncMongoMockClient()["test"]
    settings = _settings(tmp_path)

    broken_module = importlib.import_module("app.migrations.0002_build_sde_lookup_collections")

    async def _boom(db: object, settings: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(broken_module, "apply", _boom)

    with pytest.raises(RuntimeError):
        await run_migrations(db, settings)

    applied_ids = {doc["_id"] async for doc in db["_migrations"].find({}, {"_id": 1})}
    assert applied_ids == {"0001_import_raw_sde_tables"}

    monkeypatch.undo()
    await run_migrations(db, settings)

    applied_ids = {doc["_id"] async for doc in db["_migrations"].find({}, {"_id": 1})}
    assert "0002_build_sde_lookup_collections" in applied_ids
