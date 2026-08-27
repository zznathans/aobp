from collections.abc import Callable
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
from app.services import character_data, esi, locations, market_prices, sde
from app.services.locations import resolve_container_chain
from app.web import (
    format_isk,
    format_number,
    item_icon_url,
    location_label_html,
    location_label_text,
    render_page,
)

router = APIRouter(prefix="/assets", tags=["assets"])

_LIST_STYLE = """
  body { display: flex; flex-direction: column; min-height: 100vh; }
  .page {
    max-width: 70rem; margin: 0 auto; padding: 2rem 1.5rem; width: 100%; box-sizing: border-box;
  }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  h2 { font-size: 0.9rem; margin: 0 0 0.5rem; flex: 0 0 auto; }
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  .stat-card {
    background: #1a1d24;
    border: 1px solid #2a2e37;
    border-radius: 10px;
    padding: 1.25rem;
  }
  .stat-card .figure { font-size: 1.6rem; font-weight: 700; }
  .stat-card .label { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  /* This section fills whatever viewport height is left below the nav and stats, rather
     than growing the page - each table scrolls internally (via .table-scroll) once its
     rows outgrow the space it's been given (the longest-running category, most likely),
     instead of pushing the page and the shorter tables further down. */
  .categories-section {
    width: 80%; margin: 0 auto; padding: 0 1.5rem 1.5rem; box-sizing: border-box;
    flex: 1; min-height: 0; display: flex;
  }
  .categories {
    display: grid; gap: 1rem; align-items: stretch; flex: 1; min-height: 0; width: 100%;
  }
  .category-column {
    display: flex; flex-direction: column; gap: 1rem; min-width: 0; min-height: 0;
  }
  .category {
    display: flex; flex-direction: column; min-width: 0; min-height: 0; flex: 1;
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 0.75rem;
  }
  .table-scroll { flex: 1; min-height: 0; overflow-y: auto; }
  .asset-table { width: 100%; border-collapse: collapse; font-size: 0.7rem; }
  .asset-table th, .asset-table td {
    padding: 0.3rem 0.4rem; border-bottom: 1px solid #2a2e37; text-align: left;
    vertical-align: middle;
  }
  .asset-table th {
    color: #9aa4b2; font-weight: 600; font-size: 0.62rem;
    text-transform: uppercase; letter-spacing: 0.02em;
    position: sticky; top: 0; background: #1a1d24;
  }
  .asset-table td.num, .asset-table th.num { text-align: right; }
  .asset-table tr:hover td { background: #21252e; }
  .asset-item {
    display: flex; align-items: center; gap: 0.4rem; min-width: 0;
    text-decoration: none; color: inherit;
  }
  .asset-item .icon { width: 18px; height: 18px; border-radius: 3px; flex-shrink: 0; }
  .asset-item .name {
    font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .empty { color: #9aa4b2; }
  .back { display: inline-block; margin-top: 1.5rem; }
"""

_DETAIL_STYLE = """
  .page { max-width: 40rem; margin: 0 auto; padding: 2rem 1.5rem; }
  .header { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
  .header .icon { width: 48px; height: 48px; border-radius: 8px; }
  .header .name { font-size: 1.3rem; font-weight: 600; }
  .header .meta { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  h2 { font-size: 1.05rem; margin: 1.5rem 0 0.75rem; }
  .summary {
    display: flex; gap: 1.5rem; flex-wrap: wrap;
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 1rem;
  }
  .summary .figure { font-size: 1.4rem; font-weight: 700; }
  .summary .label { color: #9aa4b2; font-size: 0.8rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: right; padding: 0.5rem; border-bottom: 1px solid #2a2e37; }
  th:first-child, td:first-child { text-align: left; }
  .empty { color: #9aa4b2; }
  .back { display: inline-block; margin-top: 1.5rem; }
"""

# SDE group_id for the eight raw refined minerals (Tritanium, Pyerite, Mexallon, ...).
_MINERAL_GROUP_ID = 18

# SDE category_id covering every asteroid ore variant (Veldspar, Scordite, Ice, ...).
_ORE_CATEGORY_ID = 25

# SDE group_id for research/invention datacores (Datacore - Amarrian Starship Engineering, ...).
_DATACORE_GROUP_ID = 333

# SDE group_id for the eight standard invention decryptors (Accelerant, Symmetry, ...).
_DECRYPTOR_GROUP_ID = 1304

# SDE category_ids for planetary interaction materials: raw P0 resources ("Planetary
# Resources") plus the processed P1-P4 commodities ("Planetary Commodities").
_PLANETARY_MATERIAL_CATEGORY_IDS = frozenset({42, 43})


def _group_matcher(group_id: int) -> Callable[[dict[str, object]], bool]:
    return lambda type_doc: type_doc.get("group_id") == group_id


def _category_matcher(category_id: int) -> Callable[[dict[str, object]], bool]:
    return lambda type_doc: type_doc.get("category_id") == category_id


def _categories_matcher(category_ids: frozenset[int]) -> Callable[[dict[str, object]], bool]:
    return lambda type_doc: type_doc.get("category_id") in category_ids


def _is_compressed_ore(type_doc: dict[str, object]) -> bool:
    if type_doc.get("category_id") != _ORE_CATEGORY_ID:
        return False
    return "compressed" in str(type_doc.get("name", "")).lower()


def _is_uncompressed_ore(type_doc: dict[str, object]) -> bool:
    if type_doc.get("category_id") != _ORE_CATEGORY_ID:
        return False
    return "compressed" not in str(type_doc.get("name", "")).lower()


_CATEGORIES: dict[str, Callable[[dict[str, object]], bool]] = {
    "Minerals": _group_matcher(_MINERAL_GROUP_ID),
    "Planetary Materials": _categories_matcher(_PLANETARY_MATERIAL_CATEGORY_IDS),
    "Compressed Ore": _is_compressed_ore,
    "Ore": _is_uncompressed_ore,
    "Datacores": _group_matcher(_DATACORE_GROUP_ID),
    "Decrypters": _group_matcher(_DECRYPTOR_GROUP_ID),
}

# Each entry is one page column, top to bottom - Ore tends to run long on its own, so
# Datacores and Decrypters (both usually short) stack together in a shared column instead
# of each claiming a full-width column of their own.
_CATEGORY_COLUMNS: list[list[str]] = [
    ["Minerals", "Planetary Materials"],
    ["Compressed Ore", "Ore"],
    ["Datacores", "Decrypters"],
]

# Categories that only render when the character actually owns something in them.
_HIDE_IF_EMPTY = frozenset({"Compressed Ore"})


@dataclass
class _CategoryRow:
    type_id: int
    quantity: int
    volume: float
    value: float
    html: str


def _unit_volume(type_doc: dict[str, object]) -> float:
    return float(cast(float | int | None, type_doc.get("volume")) or 0.0)


def _unit_price(price_doc: dict[str, object] | None) -> float:
    return float(cast(float | int | None, (price_doc or {}).get("average_price")) or 0.0)


def _category_rows(
    assets: list[esi.AssetEntry],
    resolved_location_by_item_id: dict[int, int],
    type_docs: dict[int, dict[str, object]],
    price_by_type_id: dict[int, dict[str, object]],
    matches: Callable[[dict[str, object]], bool],
) -> list[_CategoryRow]:
    quantity_by_type: dict[int, int] = {}
    locations_by_type: dict[int, set[int]] = {}
    for asset in assets:
        type_doc = type_docs.get(asset.type_id)
        if type_doc is None or not matches(type_doc):
            continue
        quantity_by_type[asset.type_id] = quantity_by_type.get(asset.type_id, 0) + asset.quantity
        locations_by_type.setdefault(asset.type_id, set()).add(
            resolved_location_by_item_id[asset.item_id]
        )

    rows = []
    for type_id, quantity in quantity_by_type.items():
        type_doc = type_docs.get(type_id, {})
        name = escape(str(type_doc.get("name", f"Type {type_id}")))
        row_volume = _unit_volume(type_doc) * quantity
        row_value = _unit_price(price_by_type_id.get(type_id)) * quantity
        location_count = len(locations_by_type[type_id])
        icon = escape(item_icon_url(type_id))
        item_href = escape(f"/assets/{type_id}")
        row_html = f"""
          <tr>
            <td>
              <a class="asset-item" href="{item_href}">
                <img class="icon" src="{icon}" alt="{name}">
                <span class="name">{name}</span>
              </a>
            </td>
            <td class="num">{format_number(quantity)}</td>
            <td class="num">{format_number(row_volume)}</td>
            <td class="num"><a href="{item_href}">{location_count}</a></td>
            <td class="num">{format_isk(row_value)}</td>
          </tr>
        """
        rows.append(
            _CategoryRow(
                type_id=type_id,
                quantity=quantity,
                volume=row_volume,
                value=row_value,
                html=row_html,
            )
        )

    rows.sort(key=lambda row: row.volume, reverse=True)
    return rows


def _render_category_table(title: str, rows: list[_CategoryRow]) -> str:
    rows_html = "".join(row.html for row in rows) or (
        '<tr><td colspan="5" class="empty">None found.</td></tr>'
    )
    return f"""
      <div class="category">
        <h2>{escape(title)}</h2>
        <div class="table-scroll">
          <table class="asset-table">
            <thead>
              <tr>
                <th>Item</th><th class="num">Quantity</th><th class="num">Volume (m3)</th>
                <th class="num">Locations</th><th class="num">Est. value</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
      </div>
    """


@router.get("", response_class=HTMLResponse)
async def list_assets(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    assets = await character_data.get_character_assets(
        db, redis, settings, character.access_token, character.character_id
    )

    if not assets:
        body = '<div class="page"><h1>Assets</h1><p class="empty">No assets found.</p></div>'
        return HTMLResponse(render_page("Assets", body, _LIST_STYLE, character=character))

    # Resolving every location's *name* requires one ESI call per unresolved location, which is
    # slow on a first load with hundreds of locations - so the overview only ever counts location
    # ids (no ESI calls needed) and defers name resolution to the per-item locations page below.
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    resolved_location_by_item_id = {
        asset.item_id: resolve_container_chain(asset.location_id, assets_by_item_id)
        for asset in assets
    }

    type_ids = {asset.type_id for asset in assets}
    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    prices = await market_prices.list_market_prices(db, type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {
        cast(int, price["_id"]): price for price in prices
    }

    total_quantity = sum(asset.quantity for asset in assets)
    total_volume = sum(
        _unit_volume(type_docs.get(asset.type_id, {})) * asset.quantity for asset in assets
    )
    total_value = sum(
        _unit_price(price_by_type_id.get(asset.type_id)) * asset.quantity for asset in assets
    )
    total_locations = len(set(resolved_location_by_item_id.values()))

    stats = f"""
      <div class="stat-grid">
        <div class="stat-card">
          <div class="figure">{format_number(total_quantity)}</div>
          <div class="label">Total items</div>
        </div>
        <div class="stat-card">
          <div class="figure">{total_locations}</div>
          <div class="label">Locations</div>
        </div>
        <div class="stat-card">
          <div class="figure">{format_number(total_volume)} m3</div>
          <div class="label">Total volume</div>
        </div>
        <div class="stat-card">
          <div class="figure">{format_isk(total_value)}</div>
          <div class="label">Est. total value</div>
        </div>
      </div>
    """

    def _table_for(title: str) -> str:
        rows = _category_rows(
            assets, resolved_location_by_item_id, type_docs, price_by_type_id, _CATEGORIES[title]
        )
        if not rows and title in _HIDE_IF_EMPTY:
            return ""
        return _render_category_table(title, rows)

    category_columns_html = "".join(
        f'<div class="category-column">'
        f'{"".join(_table_for(title) for title in column_titles)}'
        f"</div>"
        for column_titles in _CATEGORY_COLUMNS
    )

    categories_columns = f"repeat({len(_CATEGORY_COLUMNS)}, minmax(0, 1fr))"
    body = f"""<div class="page">
      <h1>Assets</h1>
      {stats}
    </div>
    <div class="categories-section">
      <div class="categories" style="grid-template-columns: {categories_columns};">
        {category_columns_html}
      </div>
    </div>"""
    return HTMLResponse(render_page("Assets", body, _LIST_STYLE, character=character))


@router.get("/{type_id}", response_class=HTMLResponse)
async def item_detail(
    type_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    assets = await character_data.get_character_assets(
        db, redis, settings, character.access_token, character.character_id
    )
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    matching = [asset for asset in assets if asset.type_id == type_id]
    if not matching:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No assets of this type found")

    quantity_by_location: dict[int, int] = {}
    for asset in matching:
        location_id = resolve_container_chain(asset.location_id, assets_by_item_id)
        quantity_by_location[location_id] = (
            quantity_by_location.get(location_id, 0) + asset.quantity
        )

    # Only resolves names for the (typically handful of) locations this one item sits at,
    # unlike the overview which skips name resolution entirely - see list_assets above.
    location_info = await locations.resolve_location_info(
        db, redis, settings, character.access_token, set(quantity_by_location)
    )
    type_docs = await sde.type_docs(db, redis, settings, {type_id})
    type_doc = type_docs.get(type_id, {})
    name = escape(str(type_doc.get("name", f"Type {type_id}")))
    unit_volume = _unit_volume(type_doc)

    price_doc = await market_prices.get_market_price(db, type_id)
    adjusted_price = float(cast(float | int | None, (price_doc or {}).get("adjusted_price")) or 0.0)
    average_price = _unit_price(price_doc)

    total_quantity = sum(quantity_by_location.values())
    total_volume = unit_volume * total_quantity
    total_value = average_price * total_quantity

    icon = escape(item_icon_url(type_id))
    header = f"""
      <div class="header">
        <img class="icon" src="{icon}" alt="{name}">
        <div>
          <div class="name">{name}</div>
          <div class="meta">{format_number(unit_volume)} m3 / unit</div>
        </div>
      </div>
    """

    market_section = f"""
      <h2>Market data</h2>
      <div class="summary">
        <div>
          <div class="figure">{format_isk(average_price)}</div>
          <div class="label">Average price</div>
        </div>
        <div>
          <div class="figure">{format_isk(adjusted_price)}</div>
          <div class="label">Adjusted price</div>
        </div>
      </div>
    """

    owned_section = f"""
      <h2>What you own</h2>
      <div class="summary">
        <div>
          <div class="figure">{format_number(total_quantity)}</div>
          <div class="label">Total quantity</div>
        </div>
        <div>
          <div class="figure">{format_number(total_volume)} m3</div>
          <div class="label">Total volume</div>
        </div>
        <div>
          <div class="figure">{format_isk(total_value)}</div>
          <div class="label">Est. total value</div>
        </div>
      </div>
    """

    rows_html = "".join(
        f"""
          <tr>
            <td>
              <a href="{escape(f"/assets/locations/{location_id}")}">
                {location_label_html(location_id, location_info.get(location_id))}
              </a>
            </td>
            <td>{format_number(quantity)}</td>
          </tr>
        """
        for location_id, quantity in sorted(
            quantity_by_location.items(), key=lambda item: item[1], reverse=True
        )
    )
    locations_section = f"""
      <h2>Locations</h2>
      <table>
        <thead><tr><th>Location</th><th>Quantity</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    """

    body = f"""<div class="page">{header}
      {market_section}
      {owned_section}
      {locations_section}
      <a class="btn btn-secondary back" href="/assets">Back to assets</a>
    </div>"""
    return HTMLResponse(
        render_page(f"{name} - eve-build", body, _DETAIL_STYLE, character=character)
    )


@router.get("/locations/{location_id}", response_class=HTMLResponse)
async def location_detail(
    location_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    assets = await character_data.get_character_assets(
        db, redis, settings, character.access_token, character.character_id
    )
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    matching = [
        asset
        for asset in assets
        if resolve_container_chain(asset.location_id, assets_by_item_id) == location_id
    ]
    if not matching:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No assets at this location")

    location_info = await locations.resolve_location_info(
        db, redis, settings, character.access_token, {location_id}
    )
    location_info_for_page = location_info.get(location_id)
    location_heading = location_label_html(location_id, location_info_for_page)
    location_title = location_label_text(location_id, location_info_for_page)

    type_ids = {asset.type_id for asset in matching}
    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    prices = await market_prices.list_market_prices(db, type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {
        cast(int, price["_id"]): price for price in prices
    }

    quantity_by_type: dict[int, int] = {}
    for asset in matching:
        quantity_by_type[asset.type_id] = quantity_by_type.get(asset.type_id, 0) + asset.quantity

    total_quantity = 0
    total_volume = 0.0
    total_value = 0.0
    rows: list[tuple[float, str]] = []
    for type_id, quantity in quantity_by_type.items():
        type_doc = type_docs.get(type_id, {})
        name = escape(str(type_doc.get("name", f"Type {type_id}")))
        row_volume = _unit_volume(type_doc) * quantity
        row_value = _unit_price(price_by_type_id.get(type_id)) * quantity
        total_quantity += quantity
        total_volume += row_volume
        total_value += row_value
        icon = escape(item_icon_url(type_id))
        item_href = escape(f"/assets/{type_id}")
        rows.append(
            (
                row_volume,
                f"""
                  <tr>
                    <td>
                      <a class="asset-item" href="{item_href}">
                        <img class="icon" src="{icon}" alt="{name}">
                        <span class="name">{name}</span>
                      </a>
                    </td>
                    <td class="num">{format_number(quantity)}</td>
                    <td class="num">{format_number(row_volume)}</td>
                    <td class="num">{format_isk(row_value)}</td>
                  </tr>
                """,
            )
        )

    rows.sort(key=lambda row: row[0], reverse=True)
    rows_html = "".join(html for _, html in rows)

    stats = f"""
      <div class="stat-grid">
        <div class="stat-card">
          <div class="figure">{format_number(total_quantity)}</div>
          <div class="label">Total items</div>
        </div>
        <div class="stat-card">
          <div class="figure">{len(quantity_by_type)}</div>
          <div class="label">Distinct items</div>
        </div>
        <div class="stat-card">
          <div class="figure">{format_number(total_volume)} m3</div>
          <div class="label">Total volume</div>
        </div>
        <div class="stat-card">
          <div class="figure">{format_isk(total_value)}</div>
          <div class="label">Est. total value</div>
        </div>
      </div>
    """

    body = f"""<div class="page">
      <h1>{location_heading}</h1>
      {stats}
      <table class="asset-table">
        <thead>
          <tr>
            <th>Item</th><th class="num">Quantity</th><th class="num">Volume (m3)</th>
            <th class="num">Est. value</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <a class="btn btn-secondary back" href="/assets">Back to assets</a>
    </div>"""
    return HTMLResponse(
        render_page(f"{location_title} - eve-build", body, _LIST_STYLE, character=character)
    )
