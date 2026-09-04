from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0009_create_market_order_indexes"


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    await db["market_orders"].create_index([("region_id", 1), ("type_id", 1)])
    await db["market_order_history"].create_index(
        [("type_id", 1), ("region_id", 1), ("scraped_at", 1)]
    )
    await db["market_order_history"].create_index(
        [("order_id", 1), ("scrape_run_id", 1)], unique=True
    )
