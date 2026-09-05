import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings
from app.models.character import CharacterDocument
from app.models.plan import PlanDocument, PlanLine
from app.services import character_data, manufacturing, market_prices, sde


@dataclass
class PlanLineInput:
    type_id: int
    runs: int
    material_efficiency: int
    source_item_id: int | None = None
    location_id: int | None = None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _new_line(line_input: PlanLineInput) -> PlanLine:
    return PlanLine(
        line_id=uuid.uuid4().hex,
        type_id=line_input.type_id,
        runs=line_input.runs,
        material_efficiency=line_input.material_efficiency,
        source_item_id=line_input.source_item_id,
        location_id=line_input.location_id,
    )


async def create_plan(
    db: AsyncIOMotorDatabase, character_id: int, name: str, lines: list[PlanLineInput]
) -> PlanDocument:
    now = _now()
    doc = PlanDocument(
        _id=uuid.uuid4().hex,
        character_id=character_id,
        name=name,
        lines=[_new_line(line_input) for line_input in lines],
        created_at=now,
        updated_at=now,
    )
    await db.plans.insert_one(doc.model_dump(by_alias=True))
    return doc


async def list_plans(db: AsyncIOMotorDatabase, character_id: int) -> list[PlanDocument]:
    docs = await db.plans.find({"character_id": character_id}).sort("updated_at", -1).to_list(None)
    return [PlanDocument.model_validate(doc) for doc in docs]


async def get_plan(
    db: AsyncIOMotorDatabase, plan_id: str, character_id: int
) -> PlanDocument | None:
    doc = await db.plans.find_one({"_id": plan_id, "character_id": character_id})
    return PlanDocument.model_validate(doc) if doc is not None else None


async def delete_plan(db: AsyncIOMotorDatabase, plan_id: str, character_id: int) -> bool:
    result = await db.plans.delete_one({"_id": plan_id, "character_id": character_id})
    return result.deleted_count > 0


async def add_line(
    db: AsyncIOMotorDatabase, plan_id: str, character_id: int, line_input: PlanLineInput
) -> PlanDocument | None:
    plan = await get_plan(db, plan_id, character_id)
    if plan is None:
        return None
    plan.lines.append(_new_line(line_input))
    plan.updated_at = _now()
    await db.plans.update_one(
        {"_id": plan_id, "character_id": character_id},
        {
            "$set": {
                "lines": [line.model_dump() for line in plan.lines],
                "updated_at": plan.updated_at,
            }
        },
    )
    return plan


async def update_line(
    db: AsyncIOMotorDatabase,
    plan_id: str,
    character_id: int,
    line_id: str,
    runs: int,
    material_efficiency: int,
) -> PlanDocument | None:
    plan = await get_plan(db, plan_id, character_id)
    if plan is None:
        return None
    for line in plan.lines:
        if line.line_id == line_id:
            line.runs = runs
            line.material_efficiency = material_efficiency
            break
    plan.updated_at = _now()
    await db.plans.update_one(
        {"_id": plan_id, "character_id": character_id},
        {
            "$set": {
                "lines": [line.model_dump() for line in plan.lines],
                "updated_at": plan.updated_at,
            }
        },
    )
    return plan


async def remove_line(
    db: AsyncIOMotorDatabase, plan_id: str, character_id: int, line_id: str
) -> PlanDocument | None:
    plan = await get_plan(db, plan_id, character_id)
    if plan is None:
        return None
    plan.lines = [line for line in plan.lines if line.line_id != line_id]
    plan.updated_at = _now()
    await db.plans.update_one(
        {"_id": plan_id, "character_id": character_id},
        {
            "$set": {
                "lines": [line.model_dump() for line in plan.lines],
                "updated_at": plan.updated_at,
            }
        },
    )
    return plan


async def rename_plan(
    db: AsyncIOMotorDatabase, plan_id: str, character_id: int, name: str
) -> PlanDocument | None:
    plan = await get_plan(db, plan_id, character_id)
    if plan is None:
        return None
    plan.name = name
    plan.updated_at = _now()
    await db.plans.update_one(
        {"_id": plan_id, "character_id": character_id},
        {"$set": {"name": plan.name, "updated_at": plan.updated_at}},
    )
    return plan


@dataclass
class LineSummary:
    line: PlanLine
    blueprint_name: str
    product_type_id: int | None
    product_name: str
    requirements: list[manufacturing.MaterialRequirement]
    material_names: dict[int, str]
    cost: float
    output: float
    profit: float
    on_site_buildable: int
    global_buildable: int
    has_manufacturing_data: bool


@dataclass
class AggregatedMaterial:
    type_id: int
    name: str
    needed: int
    global_have: int
    global_missing: int


@dataclass
class PlanSummary:
    lines: list[LineSummary]
    aggregated_materials: list[AggregatedMaterial]
    total_cost: float
    total_output: float
    total_profit: float
    total_time_seconds: float


async def compute_plan_summary(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
    plan: PlanDocument,
) -> PlanSummary:
    blueprint_type_ids = {line.type_id for line in plan.lines}
    sde_blueprints = await sde.blueprint_docs(db, redis, settings, blueprint_type_ids)

    product_type_ids = {
        cast(int, doc["product_type_id"])
        for doc in sde_blueprints.values()
        if doc.get("product_type_id") is not None
    }
    material_type_ids = {
        cast(int, material["type_id"])
        for doc in sde_blueprints.values()
        for material in cast(list[dict[str, int]], doc.get("materials", []))
    }
    name_type_ids = blueprint_type_ids | product_type_ids | material_type_ids
    type_docs = await sde.type_docs(db, redis, settings, name_type_ids)

    price_type_ids = product_type_ids | material_type_ids
    prices = await market_prices.list_market_prices(db, price_type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    assets, _ = await character_data.get_merged_assets(db, redis, settings, character)
    global_totals: dict[int, int] = {}
    for asset in assets:
        global_totals[asset.type_id] = global_totals.get(asset.type_id, 0) + asset.quantity

    on_site_totals_by_location: dict[int, dict[int, int]] = {}
    location_ids = {line.location_id for line in plan.lines if line.location_id is not None}
    for location_id in location_ids:
        totals: dict[int, int] = {}
        for asset in assets:
            if asset.location_id == location_id:
                totals[asset.type_id] = totals.get(asset.type_id, 0) + asset.quantity
        on_site_totals_by_location[location_id] = totals

    aggregated_needed: dict[int, int] = {}
    line_summaries: list[LineSummary] = []
    total_cost = 0.0
    total_output = 0.0
    total_profit = 0.0
    total_time_seconds = 0.0

    for line in plan.lines:
        sde_blueprint = sde_blueprints.get(line.type_id)
        blueprint_name = str(type_docs.get(line.type_id, {}).get("name", f"Type {line.type_id}"))
        if sde_blueprint is None:
            line_summaries.append(
                LineSummary(
                    line=line,
                    blueprint_name=blueprint_name,
                    product_type_id=None,
                    product_name="",
                    requirements=[],
                    material_names={},
                    cost=0.0,
                    output=0.0,
                    profit=0.0,
                    on_site_buildable=0,
                    global_buildable=0,
                    has_manufacturing_data=False,
                )
            )
            continue

        materials = cast(list[dict[str, int]], sde_blueprint["materials"])
        product_type_id = cast(int | None, sde_blueprint.get("product_type_id"))
        product_quantity = cast(int, sde_blueprint.get("product_quantity", 1))
        product_name = (
            str(type_docs.get(product_type_id, {}).get("name", "")) if product_type_id else ""
        )

        on_site_totals = (
            on_site_totals_by_location.get(line.location_id, {})
            if line.location_id is not None
            else {}
        )
        requirements = manufacturing.compute_material_requirements(
            materials, line.material_efficiency, line.runs, on_site_totals, global_totals
        )
        on_site_buildable, global_buildable = manufacturing.compute_buildable(requirements)
        cost, output, profit = manufacturing.compute_cost_output_profit(
            materials,
            product_type_id,
            product_quantity,
            line.runs,
            line.material_efficiency,
            price_by_type_id,
        )
        total_cost += cost
        total_output += output
        total_profit += profit
        total_time_seconds += (
            cast(float, sde_blueprint.get("manufacturing_time_seconds") or 0) * line.runs
        )

        for requirement in requirements:
            aggregated_needed[requirement.type_id] = (
                aggregated_needed.get(requirement.type_id, 0) + requirement.needed
            )

        material_names = {
            cast(int, material["type_id"]): str(
                type_docs.get(material["type_id"], {}).get("name", f"Type {material['type_id']}")
            )
            for material in materials
        }

        line_summaries.append(
            LineSummary(
                line=line,
                blueprint_name=blueprint_name,
                product_type_id=product_type_id,
                product_name=product_name,
                requirements=requirements,
                material_names=material_names,
                cost=cost,
                output=output,
                profit=profit,
                on_site_buildable=on_site_buildable,
                global_buildable=global_buildable,
                has_manufacturing_data=True,
            )
        )

    aggregated_materials = [
        AggregatedMaterial(
            type_id=type_id,
            name=str(type_docs.get(type_id, {}).get("name", f"Type {type_id}")),
            needed=needed,
            global_have=global_totals.get(type_id, 0),
            global_missing=max(0, needed - global_totals.get(type_id, 0)),
        )
        for type_id, needed in sorted(aggregated_needed.items())
    ]

    return PlanSummary(
        lines=line_summaries,
        aggregated_materials=aggregated_materials,
        total_cost=total_cost,
        total_output=total_output,
        total_profit=total_profit,
        total_time_seconds=total_time_seconds,
    )
