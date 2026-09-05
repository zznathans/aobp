from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0009_drop_market_order_history"


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    await db.drop_collection("market_order_history")
