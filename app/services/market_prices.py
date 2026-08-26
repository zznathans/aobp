import asyncio
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings
from app.services import esi


async def _upsert_price(
    db: AsyncIOMotorDatabase, entry: esi.MarketPriceEntry, now: datetime
) -> None:
    await db.market_prices.update_one(
        {"_id": entry.type_id},
        {
            "$set": {
                "adjusted_price": entry.adjusted_price,
                "average_price": entry.average_price,
                "updated_at": now,
            }
        },
        upsert=True,
    )


async def refresh_market_prices(db: AsyncIOMotorDatabase, settings: Settings) -> int:
    entries = await esi.get_market_prices(settings)
    now = datetime.now(UTC).replace(tzinfo=None)

    await asyncio.gather(*(_upsert_price(db, entry, now) for entry in entries))

    return len(entries)


async def list_market_prices(
    db: AsyncIOMotorDatabase, type_ids: set[int] | None = None
) -> list[dict[str, object]]:
    query = {"_id": {"$in": list(type_ids)}} if type_ids else {}
    return await db.market_prices.find(query).to_list(None)


async def get_market_price(db: AsyncIOMotorDatabase, type_id: int) -> dict[str, object] | None:
    return await db.market_prices.find_one({"_id": type_id})
