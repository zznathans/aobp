from dataclasses import dataclass
from html import escape
from typing import cast

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import market_prices, sde
from app.web import format_isk, item_icon_url, render_page

router = APIRouter(prefix="/planetary", tags=["planetary"])

_LIST_STYLE = """
  .page { max-width: 70rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  h2 { font-size: 1.05rem; margin: 1.5rem 0 0.75rem; }
  h2:first-of-type { margin-top: 0; }
  .pi-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .pi-table th, .pi-table td {
    padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2e37; text-align: left;
    vertical-align: middle;
  }
  .pi-table th {
    color: #9aa4b2; font-weight: 600; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .pi-table td.num { text-align: right; }
  .pi-table tr:hover td { background: #1a1d24; }
  .pi-link { display: flex; align-items: center; gap: 0.6rem; }
  .pi-link .icon { width: 32px; height: 32px; border-radius: 4px; flex-shrink: 0; }
  .pi-link .name { font-weight: 600; }
  .pi-inputs { color: #9aa4b2; font-size: 0.8rem; }
  .empty { color: #9aa4b2; }
"""

_TIER_LABELS: dict[int, str] = {
    1042: "Tier 1 - Basic Commodities",
    1034: "Tier 2 - Refined Commodities",
    1040: "Tier 3 - Specialized Commodities",
    1041: "Tier 4 - Advanced Commodities",
}
_TIER_ORDER = (1042, 1034, 1040, 1041)
_OTHER_TIER = "Other"


@dataclass
class _Row:
    tier_group_id: int | None
    name: str
    html: str


@router.get("", response_class=HTMLResponse)
async def list_planet_schematics(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    schematics = await sde.list_all_planet_schematics(db)

    if not schematics:
        body = (
            '<div class="page"><h1>Planetary Industry</h1>'
            '<p class="empty">No planetary schematics found.</p></div>'
        )
        return HTMLResponse(
            render_page("Planetary Industry", body, _LIST_STYLE, character=character)
        )

    type_ids: set[int] = set()
    for schematic in schematics:
        type_ids.add(cast(dict[str, int], schematic["output"])["type_id"])
        for material in cast(list[dict[str, int]], schematic["inputs"]):
            type_ids.add(material["type_id"])

    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    prices = await market_prices.list_market_prices(db, type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    def _type_name(type_id: int) -> str:
        return str(type_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    rows: list[_Row] = []
    for schematic in schematics:
        name = str(schematic["name"])
        output = cast(dict[str, int], schematic["output"])
        inputs = cast(list[dict[str, int]], schematic["inputs"])
        output_type_id = output["type_id"]
        output_quantity = output["quantity"]

        output_value = output_quantity * market_prices.unit_price(
            price_by_type_id.get(output_type_id)
        )
        input_cost = sum(
            material["quantity"]
            * market_prices.unit_price(price_by_type_id.get(material["type_id"]))
            for material in inputs
        )
        profit = output_value - input_cost

        inputs_text = ", ".join(
            f"{_type_name(material['type_id'])} &times;{material['quantity']}"
            for material in inputs
        )

        icon = escape(item_icon_url(output_type_id))
        output_name = escape(_type_name(output_type_id))
        schematic_name = escape(name)
        cycle_minutes = cast(int, schematic["cycle_time_seconds"]) // 60

        row_html = f"""
          <tr>
            <td>
              <div class="pi-link">
                <img class="icon" src="{icon}" alt="{output_name}"
                  onerror="this.style.visibility='hidden'">
                <div>{schematic_name}</div>
              </div>
            </td>
            <td>{output_name} &times;{output_quantity}</td>
            <td class="pi-inputs">{inputs_text}</td>
            <td>{cycle_minutes} min</td>
            <td class="num">{format_isk(input_cost)}</td>
            <td class="num">{format_isk(output_value)}</td>
            <td class="num">{format_isk(profit)}</td>
          </tr>
        """
        tier_group_id = cast(dict[str, object] | None, type_docs.get(output_type_id))
        group_id = cast(int | None, tier_group_id.get("group_id")) if tier_group_id else None
        rows.append(_Row(tier_group_id=group_id, name=name, html=row_html))

    rows_by_tier: dict[str, list[_Row]] = {}
    for row in rows:
        tier_name = _TIER_LABELS.get(cast(int, row.tier_group_id), _OTHER_TIER)
        rows_by_tier.setdefault(tier_name, []).append(row)
    for tier_rows in rows_by_tier.values():
        tier_rows.sort(key=lambda r: r.name.lower())

    tier_names = [
        _TIER_LABELS[group_id] for group_id in _TIER_ORDER if _TIER_LABELS[group_id] in rows_by_tier
    ]
    if _OTHER_TIER in rows_by_tier:
        tier_names.append(_OTHER_TIER)

    headers = """
      <tr>
        <th>Schematic</th><th>Output</th><th>Inputs</th><th>Cycle</th>
        <th>Input cost</th><th>Output value</th><th>Profit / cycle</th>
      </tr>
    """
    sections = "".join(f"""
          <h2>{escape(tier_name)}</h2>
          <table class="pi-table">
            <thead>{headers}</thead>
            <tbody>{"".join(row.html for row in rows_by_tier[tier_name])}</tbody>
          </table>
        """ for tier_name in tier_names)

    body = f"""<div class="page">
      <h1>Planetary Industry</h1>
      {sections}
    </div>"""
    return HTMLResponse(render_page("Planetary Industry", body, _LIST_STYLE, character=character))
