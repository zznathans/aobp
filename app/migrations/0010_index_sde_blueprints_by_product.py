from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings

MIGRATION_ID = "0010_index_sde_blueprints_by_product"


async def apply(db: AsyncIOMotorDatabase, settings: Settings) -> None:
    await db["sde_blueprints"].create_index([("product_type_id", 1)])
