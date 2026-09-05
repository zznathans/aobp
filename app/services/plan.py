import uuid
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase


async def create_plan(
    db: AsyncIOMotorDatabase,
    character_id: int,
    target_type_id: int,
    target_quantity: int,
    build_set: frozenset[int],
) -> str:
    """Saves a plan as just enough to re-derive the same BuildResolution later via
    resolve_build_chain - not a frozen snapshot of costs/materials, which would go stale as
    prices change. Returns the new plan's id."""
    plan_id = str(uuid.uuid4())
    now = datetime.now(UTC).replace(tzinfo=None)
    await db.plans.insert_one(
        {
            "_id": plan_id,
            "character_id": character_id,
            "target_type_id": target_type_id,
            "target_quantity": target_quantity,
            "build_set": sorted(build_set),
            "created_at": now,
            "updated_at": now,
        }
    )
    return plan_id


async def get_plan(
    db: AsyncIOMotorDatabase, plan_id: str, character_id: int
) -> dict[str, object] | None:
    return await db.plans.find_one({"_id": plan_id, "character_id": character_id})


async def list_plans(db: AsyncIOMotorDatabase, character_id: int) -> list[dict[str, object]]:
    cursor = db.plans.find({"character_id": character_id}).sort("updated_at", -1)
    return await cursor.to_list(None)
