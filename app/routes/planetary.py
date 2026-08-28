from dataclasses import dataclass
from html import escape
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
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
  .pi-filters {
    display: flex; flex-wrap: wrap; gap: 1.25rem; align-items: center;
    margin-bottom: 1.5rem; font-size: 0.85rem; color: #9aa4b2;
  }
  .pi-filters label { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }
  .pi-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .pi-table-narrow { width: auto; min-width: 22rem; }
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
  .pi-link {
    display: flex; align-items: center; gap: 0.6rem;
    text-decoration: none; color: inherit;
  }
  .pi-link .icon { width: 32px; height: 32px; border-radius: 4px; flex-shrink: 0; }
  .pi-link .name { font-weight: 600; }
  .pi-inputs { color: #9aa4b2; font-size: 0.8rem; }
  .empty { color: #9aa4b2; }
"""

_DETAIL_STYLE = """
  .page { max-width: 40rem; margin: 0 auto; padding: 2rem 1.5rem; }
  .header { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
  .header .icon { width: 64px; height: 64px; border-radius: 8px; }
  .header .name { font-size: 1.3rem; font-weight: 600; }
  .header .meta { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: right; padding: 0.5rem; border-bottom: 1px solid #2a2e37; }
  th:first-child, td:first-child { text-align: left; }
  .back { display: inline-block; margin-top: 1.5rem; }
  .empty { color: #9aa4b2; }
"""

_TIER_LABELS: dict[int, str] = {
    1042: "Tier 1 - Basic Commodities",
    1034: "Tier 2 - Refined Commodities",
    1040: "Tier 3 - Specialized Commodities",
    1041: "Tier 4 - Advanced Commodities",
}
_TIER_ORDER = (1042, 1034, 1040, 1041)
_TIER_INDEX_BY_GROUP_ID: dict[int, int] = {1042: 1, 1034: 2, 1040: 3, 1041: 4}
_OTHER_TIER = "Other"
_P0_LABEL = "P0 - Raw Materials"


@dataclass
class _Row:
    tier_group_id: int | None
    name: str
    html: str


def _collect_price_type_ids(schematics: list[dict[str, object]]) -> set[int]:
    type_ids: set[int] = set()
    for schematic in schematics:
        type_ids.add(cast(dict[str, int], schematic["output"])["type_id"])
        for material in cast(list[dict[str, int]], schematic["inputs"]):
            type_ids.add(material["type_id"])
    return type_ids


def _expand_to_tier(
    type_id: int,
    quantity: float,
    floor_tier: int,
    schematic_by_output_type_id: dict[int, dict[str, object]],
    tier_index_by_type_id: dict[int, int],
) -> dict[int, float]:
    schematic = schematic_by_output_type_id.get(type_id)
    if schematic is None or tier_index_by_type_id.get(type_id, 0) <= floor_tier:
        return {type_id: quantity}

    output = cast(dict[str, int], schematic["output"])
    runs_needed = quantity / output["quantity"]
    result: dict[int, float] = {}
    for material in cast(list[dict[str, int]], schematic["inputs"]):
        sub = _expand_to_tier(
            material["type_id"],
            runs_needed * material["quantity"],
            floor_tier,
            schematic_by_output_type_id,
            tier_index_by_type_id,
        )
        for sub_type_id, sub_quantity in sub.items():
            result[sub_type_id] = result.get(sub_type_id, 0.0) + sub_quantity
    return result


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

    type_ids = _collect_price_type_ids(schematics)
    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    prices = await market_prices.list_market_prices(db, type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    def _type_name(type_id: int) -> str:
        return str(type_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    def _price(type_id: int) -> float:
        return market_prices.unit_price(price_by_type_id.get(type_id))

    output_type_ids = {cast(dict[str, int], s["output"])["type_id"] for s in schematics}
    input_type_ids = {
        material["type_id"]
        for s in schematics
        for material in cast(list[dict[str, int]], s["inputs"])
    }
    raw_material_type_ids = input_type_ids - output_type_ids

    rows: list[_Row] = []
    for schematic in schematics:
        schematic_id = schematic["_id"]
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
        detail_href = escape(f"/planetary/{schematic_id}")

        row_html = f"""
          <tr>
            <td>
              <a class="pi-link" href="{detail_href}">
                <img class="icon" src="{icon}" alt="{output_name}"
                  onerror="this.style.visibility='hidden'">
                <div>{schematic_name}</div>
              </a>
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

    _OTHER_GROUP_ID = 0
    rows_by_group_id: dict[int, list[_Row]] = {}
    for row in rows:
        group_id = row.tier_group_id if row.tier_group_id in _TIER_LABELS else _OTHER_GROUP_ID
        rows_by_group_id.setdefault(group_id, []).append(row)
    for tier_rows in rows_by_group_id.values():
        tier_rows.sort(key=lambda r: r.name.lower())

    section_group_ids = [gid for gid in _TIER_ORDER if gid in rows_by_group_id]
    if _OTHER_GROUP_ID in rows_by_group_id:
        section_group_ids.append(_OTHER_GROUP_ID)

    headers = """
      <tr>
        <th>Schematic</th><th>Output</th><th>Inputs</th><th>Cycle</th>
        <th>Input cost</th><th>Output value</th><th>Profit / cycle</th>
      </tr>
    """

    sections: list[tuple[str, str, str]] = []

    if raw_material_type_ids:
        raw_rows = sorted(raw_material_type_ids, key=lambda tid: _type_name(tid).lower())
        raw_rows_html = "".join(f"""
              <tr>
                <td>
                  <div class="pi-link">
                    <img class="icon" src="{escape(item_icon_url(type_id))}"
                      alt="{escape(_type_name(type_id))}" onerror="this.style.visibility='hidden'">
                    <div>{escape(_type_name(type_id))}</div>
                  </div>
                </td>
                <td class="num">{format_isk(_price(type_id))}</td>
              </tr>
            """ for type_id in raw_rows)
        p0_html = f"""
          <div id="tier-p0">
            <h2>{escape(_P0_LABEL)}</h2>
            <table class="pi-table pi-table-narrow">
              <thead><tr><th>Material</th><th>Price</th></tr></thead>
              <tbody>{raw_rows_html}</tbody>
            </table>
          </div>
        """
        sections.append(("tier-p0", _P0_LABEL, p0_html))

    for group_id in section_group_ids:
        tier_name = _TIER_LABELS.get(group_id, _OTHER_TIER)
        section_id = "tier-other" if group_id == _OTHER_GROUP_ID else f"tier-{group_id}"
        tier_html = f"""
          <div id="{section_id}">
            <h2>{escape(tier_name)}</h2>
            <table class="pi-table">
              <thead>{headers}</thead>
              <tbody>{"".join(row.html for row in rows_by_group_id[group_id])}</tbody>
            </table>
          </div>
        """
        sections.append((section_id, tier_name, tier_html))

    filters_html = "".join(f"""<label>
          <input type="checkbox" checked onchange="pi_toggle('{section_id}', this.checked)">
          {escape(label)}
        </label>""" for section_id, label, _ in sections)

    body = f"""<div class="page">
      <h1>Planetary Industry</h1>
      <div class="pi-filters">{filters_html}</div>
      {"".join(html for _, _, html in sections)}
      <script>
        function pi_toggle(id, show) {{
          document.getElementById(id).style.display = show ? '' : 'none';
        }}
      </script>
    </div>"""
    return HTMLResponse(render_page("Planetary Industry", body, _LIST_STYLE, character=character))


@router.get("/{schematic_id}", response_class=HTMLResponse)
async def planet_schematic_detail(
    schematic_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    schematics = await sde.list_all_planet_schematics(db)
    schematic = next((s for s in schematics if s["_id"] == schematic_id), None)
    if schematic is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Planetary schematic not found")

    page_title = f"{schematic['name']} - eve-build"

    type_ids = _collect_price_type_ids(schematics)
    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    prices = await market_prices.list_market_prices(db, type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    def _type_name(type_id: int) -> str:
        return str(type_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    schematic_by_output_type_id = {
        cast(dict[str, int], s["output"])["type_id"]: s for s in schematics
    }
    tier_index_by_type_id: dict[int, int] = {}
    for output_type_id in schematic_by_output_type_id:
        type_doc = type_docs.get(output_type_id)
        group_id = cast(int | None, type_doc.get("group_id")) if type_doc else None
        if group_id in _TIER_INDEX_BY_GROUP_ID:
            tier_index_by_type_id[output_type_id] = _TIER_INDEX_BY_GROUP_ID[group_id]

    output = cast(dict[str, int], schematic["output"])
    inputs = cast(list[dict[str, int]], schematic["inputs"])
    output_type_id = output["type_id"]
    output_quantity = output["quantity"]
    output_value = output_quantity * market_prices.unit_price(price_by_type_id.get(output_type_id))
    schematic_name = escape(str(schematic["name"]))
    output_name = escape(_type_name(output_type_id))
    icon = escape(item_icon_url(output_type_id))
    cycle_minutes = cast(int, schematic["cycle_time_seconds"]) // 60

    header = f"""
      <div class="header">
        <img class="icon" src="{icon}" alt="{output_name}" onerror="this.style.visibility='hidden'">
        <div>
          <div class="name">{schematic_name}</div>
          <div class="meta">Produces {output_name} &times;{output_quantity} &middot;
            {cycle_minutes} min cycle</div>
        </div>
      </div>
    """

    own_tier = tier_index_by_type_id.get(output_type_id, 0)
    if own_tier < 1:
        body = f"""<div class="page">{header}
          <p class="empty">No tier data available for this schematic.</p>
          <a class="btn btn-secondary back" href="/planetary">Back to planetary industry</a>
        </div>"""
        return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))

    rows_html = []
    for floor in range(own_tier):
        expanded: dict[int, float] = {}
        for material in inputs:
            sub = _expand_to_tier(
                material["type_id"],
                material["quantity"],
                floor,
                schematic_by_output_type_id,
                tier_index_by_type_id,
            )
            for type_id, quantity in sub.items():
                expanded[type_id] = expanded.get(type_id, 0.0) + quantity

        cost = sum(
            quantity * market_prices.unit_price(price_by_type_id.get(type_id))
            for type_id, quantity in expanded.items()
        )
        profit = output_value - cost
        tier_label = f"From P{floor}"

        rows_html.append(f"""
          <tr>
            <td>{escape(tier_label)}</td>
            <td>{format_isk(cost)}</td>
            <td>{format_isk(output_value)}</td>
            <td>{format_isk(profit)}</td>
          </tr>
        """)

    body = f"""<div class="page">{header}
      <table>
        <thead>
          <tr><th>Starting tier</th><th>Material cost</th><th>Output value</th><th>Profit</th></tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
      <a class="btn btn-secondary back" href="/planetary">Back to planetary industry</a>
    </div>"""
    return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))
