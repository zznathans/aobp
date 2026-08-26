import importlib
import logging
import pkgutil
from datetime import UTC, datetime
from typing import Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

import app.migrations as migrations_package
from app.core.config import Settings

logger = logging.getLogger("eve-build.migrations")


class Migration(Protocol):
    MIGRATION_ID: str

    async def apply(self, db: AsyncIOMotorDatabase, settings: Settings) -> None: ...


def _discover_migrations() -> list[Migration]:
    modules = []
    for module_info in sorted(
        pkgutil.iter_modules(migrations_package.__path__), key=lambda m: m.name
    ):
        if not module_info.name[0].isdigit():
            continue
        module = importlib.import_module(f"app.migrations.{module_info.name}")
        modules.append(module)
    return modules  # type: ignore[return-value]


async def run_migrations(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    applied_ids = {doc["_id"] async for doc in db["_migrations"].find({}, {"_id": 1})}

    for migration in _discover_migrations():
        if migration.MIGRATION_ID in applied_ids:
            logger.info("Skipping already-applied migration %s", migration.MIGRATION_ID)
            continue
        logger.info("Applying migration %s", migration.MIGRATION_ID)
        await migration.apply(db, settings)
        await db["_migrations"].insert_one(
            {"_id": migration.MIGRATION_ID, "applied_at": datetime.now(UTC).replace(tzinfo=None)}
        )
        logger.info("Applied migration %s", migration.MIGRATION_ID)
