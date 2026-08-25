import math
from dataclasses import dataclass
from html import escape
from typing import cast
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import esi, locations, sde
from app.web import gauge_cell_html, icon_url, render_page

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

_LIST_STYLE = """
  .page { max-width: 70rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  .filters {
    display: flex; gap: 1.25rem; align-items: center;
    margin-bottom: 1.25rem; font-size: 0.85rem; color: #9aa4b2;
  }
  .filters label { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; }
  .filters select {
    margin-left: auto; background: #1a1d24; color: #e6e6e6;
    border: 1px solid #2a2e37; border-radius: 6px; padding: 0.35rem 0.5rem;
    font-size: 0.85rem;
  }
  .bp-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .bp-table th, .bp-table td {
    padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2e37; text-align: left;
    vertical-align: middle;
  }
  .bp-table th {
    color: #9aa4b2; font-weight: 600; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .bp-table th a { color: inherit; text-decoration: none; white-space: nowrap; }
  .bp-table th a:hover { color: #e6e6e6; }
  .bp-table tr:hover td { background: #1a1d24; }
  .bp-link {
    display: flex; align-items: center; gap: 0.6rem;
    text-decoration: none; color: inherit;
  }
  .bp-link .icon { width: 32px; height: 32px; border-radius: 4px; flex-shrink: 0; }
  .bp-link .name { font-weight: 600; }
  .bp-link .sub { color: #9aa4b2; font-size: 0.75rem; margin-top: 0.1rem; }
  .empty { color: #9aa4b2; }
"""

_DETAIL_STYLE = """
  .page { max-width: 40rem; margin: 0 auto; padding: 2rem 1.5rem; }
  .header { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
  .header .icon { width: 64px; height: 64px; border-radius: 8px; }
  .header .name { font-size: 1.3rem; font-weight: 600; }
  .header .meta { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  .summary {
    display: flex; gap: 1.5rem; margin-bottom: 1.5rem;
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 1rem;
  }
  .summary .figure { font-size: 1.4rem; font-weight: 700; }
  .summary .label { color: #9aa4b2; font-size: 0.8rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: right; padding: 0.5rem; border-bottom: 1px solid #2a2e37; }
  th:first-child, td:first-child { text-align: left; }
  .short { color: #f0625a; }
  .back { display: inline-block; margin-top: 1.5rem; }
"""


def _material_quantity_per_run(base_quantity: int, material_efficiency: int) -> int:
    return max(1, math.ceil(base_quantity * (1 - material_efficiency / 100)))


def _resolve_container_chain(location_id: int, assets_by_item_id: dict[int, esi.AssetEntry]) -> int:
    """A blueprint/asset location_id can be another item's item_id if it's sitting inside
    a container (which can itself be inside another container). Walk that chain using the
    already-fetched asset list until reaching a real station/structure id, so we never try
    to resolve a container's item_id as if it were a station or structure."""
    current = location_id
    visited: set[int] = set()
    while current in assets_by_item_id and current not in visited:
        visited.add(current)
        asset = assets_by_item_id[current]
        if asset.location_type != "item":
            return asset.location_id
        current = asset.location_id
    return current


def _readiness_percentages(
    materials: list[dict[str, int]],
    material_efficiency: int,
    on_site_totals: dict[int, int],
    global_totals: dict[int, int],
) -> tuple[float, float]:
    if not materials:
        return 100.0, 100.0

    needed_total = 0
    on_site_have_total = 0
    global_have_total = 0
    for material in materials:
        type_id = material["type_id"]
        needed = _material_quantity_per_run(material["quantity"], material_efficiency)
        needed_total += needed
        on_site_have_total += min(on_site_totals.get(type_id, 0), needed)
        global_have_total += min(global_totals.get(type_id, 0), needed)

    return (
        100.0 * on_site_have_total / needed_total,
        100.0 * global_have_total / needed_total,
    )


_FILTER_OPTIONS = ("original", "copy", "t2")
_DEFAULT_FILTERS = frozenset({"original"})
_SORT_COLUMNS = ("name", "me", "te", "onsite", "global")
_SORT_LABELS = {
    "name": "Blueprint",
    "me": "ME",
    "te": "TE",
    "onsite": "On-site",
    "global": "All assets",
}


@dataclass
class _Row:
    name: str
    is_copy: bool
    is_t2: bool
    me: int
    te: int
    on_site_pct: float
    global_pct: float
    location_id: int
    html: str


def _query_string(selected: frozenset[str], sort: str, direction: str, location: str) -> str:
    params = [
        ("f", "1"),
        *[("show", value) for value in selected],
        ("sort", sort),
        ("dir", direction),
        *([("location", location)] if location else []),
    ]
    return urlencode(params)


def _sort_header(
    column: str, selected: frozenset[str], current_sort: str, current_dir: str, location: str
) -> str:
    label = _SORT_LABELS[column]
    if column == current_sort:
        next_dir = "desc" if current_dir == "asc" else "asc"
        label += " &#9650;" if current_dir == "asc" else " &#9660;"
    else:
        next_dir = "asc"
    href = escape(f"?{_query_string(selected, column, next_dir, location)}")
    return f'<th><a href="{href}">{label}</a></th>'


def _render_filters_form(
    selected: frozenset[str],
    sort: str,
    direction: str,
    location: str,
    location_options: list[tuple[int, str]],
) -> str:
    checkboxes_html = "".join(f"""<label>
          <input type="checkbox" name="show" value="{option}"
            {"checked" if option in selected else ""} onchange="this.form.submit()">
          {option.capitalize() if option != "t2" else "T2"}
        </label>""" for option in _FILTER_OPTIONS)

    location_option_tags = "".join(
        f'<option value="{escape(str(loc_id))}" '
        f'{"selected" if str(loc_id) == location else ""}>'
        f"{escape(loc_name)}</option>"
        for loc_id, loc_name in location_options
    )

    return f"""
      <form method="get" class="filters">
        <input type="hidden" name="f" value="1">
        <input type="hidden" name="sort" value="{escape(sort)}">
        <input type="hidden" name="dir" value="{escape(direction)}">
        {checkboxes_html}
        <select name="location" onchange="this.form.submit()">
          <option value="">All locations</option>
          {location_option_tags}
        </select>
      </form>
    """


@router.get("", response_class=HTMLResponse)
async def list_blueprints(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    f: str | None = Query(default=None),
    show: list[str] = Query(default=[]),
    sort: str = Query(default="name"),
    dir: str = Query(default="asc"),  # noqa: A002
    location: str = Query(default=""),
) -> HTMLResponse:
    selected = frozenset(show) & set(_FILTER_OPTIONS) if f is not None else _DEFAULT_FILTERS
    sort = sort if sort in _SORT_COLUMNS else "name"
    direction = dir if dir in ("asc", "desc") else "asc"

    blueprints = await esi.get_character_blueprints(
        settings, character.access_token, character.character_id
    )
    type_docs = await sde.type_docs(db, redis, settings, {bp.type_id for bp in blueprints})

    if not blueprints:
        filters_form = _render_filters_form(selected, sort, direction, location, [])
        body = f'<div class="page"><h1>Blueprints</h1>{filters_form}' + (
            '<p class="empty">No blueprints found.</p></div>'
        )
        return HTMLResponse(render_page("Blueprints", body, _LIST_STYLE, character=character))

    assets = await esi.get_character_assets(
        settings, character.access_token, character.character_id
    )
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    global_totals: dict[int, int] = {}
    assets_by_location: dict[int, dict[int, int]] = {}
    for asset in assets:
        global_totals[asset.type_id] = global_totals.get(asset.type_id, 0) + asset.quantity
        location_totals = assets_by_location.setdefault(asset.location_id, {})
        location_totals[asset.type_id] = location_totals.get(asset.type_id, 0) + asset.quantity

    sde_by_type_id = await sde.blueprint_docs(
        db, redis, settings, {bp.type_id for bp in blueprints}
    )

    resolved_location_by_item_id = {
        bp.item_id: _resolve_container_chain(bp.location_id, assets_by_item_id) for bp in blueprints
    }
    location_names = await locations.resolve_location_names(
        db, redis, settings, character.access_token, set(resolved_location_by_item_id.values())
    )

    parsed_rows = []
    for bp in blueprints:
        is_copy = bp.quantity == -2 or bp.runs != -1
        type_doc = type_docs.get(bp.type_id, {})
        name = escape(str(type_doc.get("name", f"Type {bp.type_id}")))
        is_t2 = type_doc.get("tech_level") == 2
        sub = "Copy" if is_copy else "Original"
        if is_copy:
            sub += f" &middot; {bp.runs} runs"

        sde_doc = sde_by_type_id.get(bp.type_id)
        if sde_doc is not None:
            on_site_pct, global_pct = _readiness_percentages(
                cast(list[dict[str, int]], sde_doc["materials"]),
                bp.material_efficiency,
                assets_by_location.get(bp.location_id, {}),
                global_totals,
            )
            on_site_gauge = gauge_cell_html(on_site_pct)
            global_gauge = gauge_cell_html(global_pct)
        else:
            on_site_pct = global_pct = -1.0
            on_site_gauge = global_gauge = '<span class="empty">&mdash;</span>'

        me_gauge = gauge_cell_html(
            100.0 * bp.material_efficiency / 10, f"{bp.material_efficiency}/10"
        )
        te_gauge = gauge_cell_html(100.0 * bp.time_efficiency / 20, f"{bp.time_efficiency}/20")

        resolved_location_id = resolved_location_by_item_id[bp.item_id]
        location_label = escape(
            location_names.get(resolved_location_id) or f"Location {resolved_location_id}"
        )

        item_href = escape(f"/blueprints/{bp.item_id}")
        row_html = f"""
          <tr>
            <td>
              <a class="bp-link" href="{item_href}">
                <img class="icon" src="{escape(icon_url(bp.type_id, is_copy))}" alt="{name}">
                <div><div class="name">{name}</div><div class="sub">{sub}</div></div>
              </a>
            </td>
            <td>{location_label}</td>
            <td>{me_gauge}</td>
            <td>{te_gauge}</td>
            <td>{on_site_gauge}</td>
            <td>{global_gauge}</td>
          </tr>
        """
        parsed_rows.append(
            _Row(
                name=name,
                is_copy=is_copy,
                is_t2=bool(is_t2),
                me=bp.material_efficiency,
                te=bp.time_efficiency,
                on_site_pct=on_site_pct,
                global_pct=global_pct,
                location_id=resolved_location_id,
                html=row_html,
            )
        )

    location_options = sorted(
        {
            (loc_id, location_names.get(loc_id) or f"Location {loc_id}")
            for loc_id in resolved_location_by_item_id.values()
        },
        key=lambda option: option[1].lower(),
    )
    filters_form = _render_filters_form(selected, sort, direction, location, location_options)

    visible_rows = [
        row
        for row in parsed_rows
        if ("copy" in selected if row.is_copy else "original" in selected)
        and (not row.is_t2 or "t2" in selected)
        and (not location or str(row.location_id) == location)
    ]

    sort_keys = {
        "name": lambda r: r.name.lower(),
        "me": lambda r: r.me,
        "te": lambda r: r.te,
        "onsite": lambda r: r.on_site_pct,
        "global": lambda r: r.global_pct,
    }
    visible_rows.sort(key=sort_keys[sort], reverse=(direction == "desc"))

    headers = (
        _sort_header("name", selected, sort, direction, location)
        + "<th>Location</th>"
        + "".join(
            _sort_header(column, selected, sort, direction, location)
            for column in _SORT_COLUMNS[1:]
        )
    )
    rows_html = "".join(row.html for row in visible_rows) or (
        '<tr><td colspan="6" class="empty">No blueprints match the current filters.</td></tr>'
    )

    body = f"""<div class="page">
      <h1>Blueprints</h1>
      {filters_form}
      <table class="bp-table">
        <thead><tr>{headers}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>"""
    return HTMLResponse(render_page("Blueprints", body, _LIST_STYLE, character=character))


@router.get("/{item_id}", response_class=HTMLResponse)
async def blueprint_detail(
    item_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    blueprints = await esi.get_character_blueprints(
        settings, character.access_token, character.character_id
    )
    blueprint = next((bp for bp in blueprints if bp.item_id == item_id), None)
    if blueprint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blueprint not found")

    assets = await esi.get_character_assets(
        settings, character.access_token, character.character_id
    )
    assets_by_item_id = {asset.item_id: asset for asset in assets}

    is_copy = blueprint.quantity == -2 or blueprint.runs != -1
    resolved_location_id = _resolve_container_chain(blueprint.location_id, assets_by_item_id)
    location_names = await locations.resolve_location_names(
        db, redis, settings, character.access_token, {resolved_location_id}
    )
    location_label = location_names.get(resolved_location_id) or f"Location {resolved_location_id}"

    sde_blueprints = await sde.blueprint_docs(db, redis, settings, {blueprint.type_id})
    sde_blueprint = sde_blueprints.get(blueprint.type_id)
    type_docs = await sde.type_docs(db, redis, settings, {blueprint.type_id})
    blueprint_type_name = type_docs.get(blueprint.type_id, {}).get("name")
    blueprint_name = escape(str(blueprint_type_name or f"Type {blueprint.type_id}"))
    blueprint_icon_url = escape(icon_url(blueprint.type_id, is_copy))

    header = f"""
      <div class="header">
        <img class="icon" src="{blueprint_icon_url}" alt="{blueprint_name}">
        <div>
          <div class="name">{blueprint_name}</div>
          <div class="meta">ME {blueprint.material_efficiency} / TE {blueprint.time_efficiency}
            &middot; {"Copy" if is_copy else "Original"}
            {f"({blueprint.runs} runs)" if is_copy else ""}</div>
          <div class="meta">{escape(location_label)}</div>
        </div>
      </div>
    """

    if sde_blueprint is None:
        body = f"""<div class="page">{header}
          <p class="empty">No manufacturing data available for this blueprint.</p>
          <a class="btn btn-secondary back" href="/blueprints">Back to blueprints</a>
        </div>"""
        return HTMLResponse(
            render_page(f"{blueprint_name} - aobp", body, _DETAIL_STYLE, character=character)
        )

    on_site_totals: dict[int, int] = {}
    global_totals: dict[int, int] = {}
    for asset in assets:
        global_totals[asset.type_id] = global_totals.get(asset.type_id, 0) + asset.quantity
        if asset.location_id == blueprint.location_id:
            on_site_totals[asset.type_id] = on_site_totals.get(asset.type_id, 0) + asset.quantity

    materials = cast(list[dict[str, int]], sde_blueprint["materials"])
    material_type_ids = {m["type_id"] for m in materials}
    material_docs = await sde.type_docs(db, redis, settings, material_type_ids)

    rows = []
    on_site_buildable = math.inf
    global_buildable = math.inf
    for material in materials:
        type_id = material["type_id"]
        needed = _material_quantity_per_run(material["quantity"], blueprint.material_efficiency)
        on_site_have = on_site_totals.get(type_id, 0)
        global_have = global_totals.get(type_id, 0)
        on_site_buildable = min(on_site_buildable, on_site_have // needed)
        global_buildable = min(global_buildable, global_have // needed)
        on_site_missing = max(0, needed - on_site_have)
        global_missing = max(0, needed - global_have)
        material_name = material_docs.get(type_id, {}).get("name")
        name = escape(str(material_name or f"Type {type_id}"))
        on_site_cell: str = str(on_site_have)
        if on_site_missing:
            on_site_cell = f'{on_site_have} <span class="short">(-{on_site_missing})</span>'
        global_cell: str = str(global_have)
        if global_missing:
            global_cell = f'{global_have} <span class="short">(-{global_missing})</span>'
        rows.append(f"""
          <tr>
            <td>{name}</td>
            <td>{needed}</td>
            <td>{on_site_cell}</td>
            <td>{global_cell}</td>
          </tr>
        """)

    if not materials:
        on_site_buildable = 0
        global_buildable = 0

    body = f"""<div class="page">{header}
      <div class="summary">
        <div>
          <div class="figure">{int(on_site_buildable)}</div>
          <div class="label">Buildable on-site</div>
        </div>
        <div>
          <div class="figure">{int(global_buildable)}</div>
          <div class="label">Buildable (all assets)</div>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>Material</th><th>Needed / run</th><th>On-site</th><th>All assets</th></tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
      <a class="btn btn-secondary back" href="/blueprints">Back to blueprints</a>
    </div>"""
    return HTMLResponse(
        render_page(f"{blueprint_name} - aobp", body, _DETAIL_STYLE, character=character)
    )
