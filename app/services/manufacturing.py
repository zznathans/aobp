import math
from dataclasses import dataclass

from app.services import market_prices


def material_quantity_per_run(base_quantity: int, material_efficiency: int) -> int:
    return max(1, math.ceil(base_quantity * (1 - material_efficiency / 100)))


@dataclass
class MaterialRequirement:
    type_id: int
    per_run_needed: int
    needed: int
    on_site_have: int
    global_have: int
    on_site_missing: int
    global_missing: int


def compute_material_requirements(
    materials: list[dict[str, int]],
    material_efficiency: int,
    runs: int,
    on_site_totals: dict[int, int],
    global_totals: dict[int, int],
) -> list[MaterialRequirement]:
    requirements = []
    for material in materials:
        type_id = material["type_id"]
        per_run_needed = material_quantity_per_run(material["quantity"], material_efficiency)
        needed = per_run_needed * runs
        on_site_have = on_site_totals.get(type_id, 0)
        global_have = global_totals.get(type_id, 0)
        requirements.append(
            MaterialRequirement(
                type_id=type_id,
                per_run_needed=per_run_needed,
                needed=needed,
                on_site_have=on_site_have,
                global_have=global_have,
                on_site_missing=max(0, needed - on_site_have),
                global_missing=max(0, needed - global_have),
            )
        )
    return requirements


def compute_buildable(requirements: list[MaterialRequirement]) -> tuple[int, int]:
    """Returns (on_site_buildable, global_buildable) - how many runs' worth of this
    blueprint's materials are on hand, independent of how many runs were requested."""
    if not requirements:
        return 0, 0
    on_site = min(req.on_site_have // req.per_run_needed for req in requirements)
    glob = min(req.global_have // req.per_run_needed for req in requirements)
    return on_site, glob


def compute_cost_output_profit(
    materials: list[dict[str, int]],
    product_type_id: int | None,
    product_quantity: int,
    runs: int,
    material_efficiency: int,
    price_by_type_id: dict[int, dict[str, object]],
) -> tuple[float, float, float]:
    cost_per_run = sum(
        material_quantity_per_run(material["quantity"], material_efficiency)
        * market_prices.unit_price(price_by_type_id.get(material["type_id"]))
        for material in materials
    )
    cost_total = cost_per_run * runs
    output_total = 0.0
    if product_type_id is not None:
        output_total = (
            product_quantity
            * runs
            * market_prices.unit_price(price_by_type_id.get(product_type_id))
        )
    return cost_total, output_total, output_total - cost_total
