from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0010_create_plans_indexes"


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    await db["plans"].create_index([("character_id", 1)])
    await db["plans"].create_index([("character_id", 1), ("updated_at", -1)])
