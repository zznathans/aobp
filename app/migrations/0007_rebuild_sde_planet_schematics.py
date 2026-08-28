import importlib

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0007_rebuild_sde_planet_schematics"

# 0006_build_sde_planet_schematics originally read planetSchematics/planetSchematicsTypeMap
# from Mongo tables that migration 0001 never actually imported (see 387c8eb), so on any
# database where 0006 already ran, it recorded itself as applied while leaving
# sde_planet_schematics empty. 0006 itself was fixed to read the gzip files directly, but
# fixing its code doesn't make the runner re-call it - a migration whose top-level ID is
# already recorded is skipped outright (app/migrations/runner.py). This migration just
# re-runs the now-correct import under a fresh ID so already-affected databases get backfilled.
_0006 = importlib.import_module("app.migrations.0006_build_sde_planet_schematics")


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    await _0006.apply(db, settings)
