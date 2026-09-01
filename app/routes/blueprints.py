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
from app.deps import get_current_character, get_current_character_optional
from app.models.character import CharacterDocument
from app.services import character_data, locations, market_prices, sde
from app.services.locations import resolve_container_chain as _resolve_container_chain
from app.web import (
    format_isk,
    gauge_cell_html,
    icon_url,
    location_label_html,
    location_label_text,
    render_page,
)

router = APIRouter(prefix="/blueprints", tags=["blueprints"])

_LIST_STYLE = "/static/blueprints-list.css"
_DETAIL_STYLE = "/static/blueprints-detail.css"


_REACTIONS_ACTIVITY_ID = 11


def _material_quantity_per_run(base_quantity: int, material_efficiency: int) -> int:
    return max(1, math.ceil(base_quantity * (1 - material_efficiency / 100)))


def _tech_level_label(is_reaction: bool, is_t2: bool) -> str:
    if is_reaction:
        return "Reaction formula"
    return "T2" if is_t2 else "T1"


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


_OTHER_CATEGORY = "Other"


@dataclass
class _Row:
    name: str
    search_name: str
    is_copy: bool
    is_t2: bool
    me: int
    te: int
    on_site_pct: float
    global_pct: float
    location_id: int
    category: str
    html: str


def _query_string(
    selected: frozenset[str], sort: str, direction: str, location: str, search: str
) -> str:
    params = [
        ("f", "1"),
        *[("show", value) for value in selected],
        ("sort", sort),
        ("dir", direction),
        *([("location", location)] if location else []),
        *([("search", search)] if search else []),
    ]
    return urlencode(params)


def _sort_header(
    column: str,
    selected: frozenset[str],
    current_sort: str,
    current_dir: str,
    location: str,
    search: str,
) -> str:
    label = _SORT_LABELS[column]
    if column == current_sort:
        next_dir = "desc" if current_dir == "asc" else "asc"
        label += " &#9650;" if current_dir == "asc" else " &#9660;"
    else:
        next_dir = "asc"
    href = escape(f"?{_query_string(selected, column, next_dir, location, search)}")
    return f'<th><a href="{href}">{label}</a></th>'


def _render_filters_form(
    selected: frozenset[str],
    sort: str,
    direction: str,
    location: str,
    search: str,
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
        <input type="text" name="search" value="{escape(search)}" placeholder="Search by name">
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
    search: str = Query(default=""),
) -> HTMLResponse:
    selected = frozenset(show) & set(_FILTER_OPTIONS) if f is not None else _DEFAULT_FILTERS
    sort = sort if sort in _SORT_COLUMNS else "name"
    direction = dir if dir in ("asc", "desc") else "asc"
    search_query = search.strip().lower()

    blueprints, corp_blueprints_included = await character_data.get_merged_blueprints(
        db, redis, settings, character
    )

    catalog_link = (
        '<a class="btn btn-secondary catalog-link" href="/blueprints/catalog">'
        "Search all blueprints</a>"
    )

    if not blueprints:
        filters_form = _render_filters_form(selected, sort, direction, location, search, [])
        body = f'<div class="page"><h1>Blueprints</h1>{catalog_link}{filters_form}' + (
            '<p class="empty">No blueprints found.</p></div>'
        )
        return HTMLResponse(render_page("Blueprints", body, _LIST_STYLE, character=character))

    sde_by_type_id = await sde.blueprint_docs(
        db, redis, settings, {bp.type_id for bp in blueprints}
    )
    product_type_ids = {
        cast(int, sde_doc["product_type_id"])
        for sde_doc in sde_by_type_id.values()
        if sde_doc.get("product_type_id") is not None
    }
    type_docs = await sde.type_docs(
        db, redis, settings, {bp.type_id for bp in blueprints} | product_type_ids
    )
    category_ids = {
        cast(int, type_docs[product_type_id]["category_id"])
        for product_type_id in product_type_ids
        if type_docs.get(product_type_id, {}).get("category_id") is not None
    }
    category_docs = await sde.category_docs(db, redis, settings, category_ids)

    assets, corp_assets_included = await character_data.get_merged_assets(
        db, redis, settings, character
    )
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    global_totals: dict[int, int] = {}
    assets_by_location: dict[int, dict[int, int]] = {}
    for asset in assets:
        global_totals[asset.type_id] = global_totals.get(asset.type_id, 0) + asset.quantity
        location_totals = assets_by_location.setdefault(asset.location_id, {})
        location_totals[asset.type_id] = location_totals.get(asset.type_id, 0) + asset.quantity

    resolved_location_by_item_id = {
        bp.item_id: _resolve_container_chain(bp.location_id, assets_by_item_id) for bp in blueprints
    }
    location_info = await locations.resolve_location_info(
        db, redis, settings, character.access_token, set(resolved_location_by_item_id.values())
    )

    parsed_rows = []
    for bp in blueprints:
        is_copy = bp.quantity == -2 or bp.runs != -1
        type_doc = type_docs.get(bp.type_id, {})
        raw_name = str(type_doc.get("name", f"Type {bp.type_id}"))
        name = escape(raw_name)
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

        product_type_id = sde_doc.get("product_type_id") if sde_doc is not None else None
        product_category_id = (
            type_docs.get(cast(int, product_type_id), {}).get("category_id")
            if product_type_id is not None
            else None
        )
        category = _OTHER_CATEGORY
        if product_category_id is not None:
            category_name = category_docs.get(cast(int, product_category_id), {}).get("name")
            if category_name:
                category = str(category_name)

        me_gauge = gauge_cell_html(
            100.0 * bp.material_efficiency / 10, f"{bp.material_efficiency}/10"
        )
        te_gauge = gauge_cell_html(100.0 * bp.time_efficiency / 20, f"{bp.time_efficiency}/20")

        resolved_location_id = resolved_location_by_item_id[bp.item_id]
        location_label = location_label_html(
            resolved_location_id, location_info.get(resolved_location_id)
        )

        item_href = escape(f"/blueprints/{bp.item_id}")
        bp_icon_url = escape(icon_url(bp.type_id, is_copy))
        row_html = f"""
          <tr>
            <td>
              <a class="bp-link" href="{item_href}">
                <img class="icon" src="{bp_icon_url}" alt="{name}"
                  onerror="this.style.visibility='hidden'">
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
                search_name=raw_name.lower(),
                is_copy=is_copy,
                is_t2=bool(is_t2),
                me=bp.material_efficiency,
                te=bp.time_efficiency,
                on_site_pct=on_site_pct,
                global_pct=global_pct,
                location_id=resolved_location_id,
                category=category,
                html=row_html,
            )
        )

    location_options = sorted(
        {
            (loc_id, location_label_text(loc_id, location_info.get(loc_id)))
            for loc_id in resolved_location_by_item_id.values()
        },
        key=lambda option: option[1].lower(),
    )
    filters_form = _render_filters_form(
        selected, sort, direction, location, search, location_options
    )

    visible_rows = [
        row
        for row in parsed_rows
        if ("copy" in selected if row.is_copy else "original" in selected)
        and (not row.is_t2 or "t2" in selected)
        and (not location or str(row.location_id) == location)
        and (not search_query or search_query in row.search_name)
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
        _sort_header("name", selected, sort, direction, location, search)
        + "<th>Location</th>"
        + "".join(
            _sort_header(column, selected, sort, direction, location, search)
            for column in _SORT_COLUMNS[1:]
        )
    )
    if not visible_rows:
        sections = f"""
          <table class="bp-table">
            <thead><tr>{headers}</tr></thead>
            <tbody>
              <tr><td colspan="6" class="empty">No blueprints match the current filters.</td></tr>
            </tbody>
          </table>
        """
    else:
        rows_by_category: dict[str, list[_Row]] = {}
        for row in visible_rows:
            rows_by_category.setdefault(row.category, []).append(row)

        category_names = sorted(
            (name for name in rows_by_category if name != _OTHER_CATEGORY), key=str.lower
        )
        if _OTHER_CATEGORY in rows_by_category:
            category_names.append(_OTHER_CATEGORY)

        sections = "".join(f"""
              <h2>{escape(category_name)}</h2>
              <table class="bp-table">
                <thead><tr>{headers}</tr></thead>
                <tbody>{"".join(row.html for row in rows_by_category[category_name])}</tbody>
              </table>
            """ for category_name in category_names)

    corp_note = (
        '<p class="empty">Includes corporation blueprints and/or assets.</p>'
        if corp_blueprints_included or corp_assets_included
        else ""
    )
    body = f"""<div class="page">
      <h1>Blueprints</h1>
      {catalog_link}
      {corp_note}
      {filters_form}
      {sections}
    </div>"""
    return HTMLResponse(render_page("Blueprints", body, _LIST_STYLE, character=character))


@router.get("/catalog", response_class=HTMLResponse)
async def blueprint_catalog(
    character: CharacterDocument | None = Depends(get_current_character_optional),
    db: AsyncIOMotorDatabase = Depends(get_database),
    q: str = Query(default=""),
) -> HTMLResponse:
    query = q.strip()

    if len(query) >= 2:
        docs = await sde.search_blueprints_by_name(db, query)
        if not docs:
            results_html = '<p class="empty">No blueprints match your search.</p>'
        else:
            rows_html = "".join(f"""
                  <tr>
                    <td>
                      <a class="bp-link" href="/blueprints/catalog/{doc['_id']}">
                        <img class="icon" src="{escape(icon_url(cast(int, doc['_id'])))}"
                          alt="{escape(str(doc['name']))}" onerror="this.style.visibility='hidden'">
                        <div class="name">{escape(str(doc["name"]))}
                          {" &middot; T2" if doc.get("tech_level") == 2 else ""}</div>
                      </a>
                    </td>
                  </tr>
                """ for doc in docs)
            results_html = f"""
              <table class="bp-table">
                <thead><tr><th>Blueprint</th></tr></thead>
                <tbody>{rows_html}</tbody>
              </table>
            """
    elif query:
        results_html = '<p class="empty">Keep typing - search needs at least 2 characters.</p>'
    else:
        results_html = ""

    search_form = f"""
      <form method="get" class="filters">
        <input type="text" name="q" value="{escape(query)}"
          placeholder="Search all blueprints by name" autofocus>
      </form>
    """
    body = f"""<div class="page">
      <h1>Blueprint Catalog</h1>
      {search_form}
      {results_html}
    </div>"""
    return HTMLResponse(render_page("Blueprint Catalog", body, _LIST_STYLE, character=character))


@router.get("/catalog/{type_id}", response_class=HTMLResponse)
async def catalog_blueprint_detail(
    type_id: int,
    character: CharacterDocument | None = Depends(get_current_character_optional),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    sde_blueprints = await sde.blueprint_docs(db, redis, settings, {type_id})
    sde_blueprint = sde_blueprints.get(type_id)
    type_docs = await sde.type_docs(db, redis, settings, {type_id})
    blueprint_type_doc = type_docs.get(type_id)
    if sde_blueprint is None or blueprint_type_doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blueprint not found")

    blueprint_name = escape(str(blueprint_type_doc.get("name", f"Type {type_id}")))
    is_reaction = sde_blueprint.get("activity_id") == _REACTIONS_ACTIVITY_ID
    is_t2 = blueprint_type_doc.get("tech_level") == 2
    blueprint_icon_url = escape(icon_url(type_id))
    page_title = f"{blueprint_name} - eve-build"

    materials = cast(list[dict[str, int]], sde_blueprint["materials"])
    product_type_id = cast(int | None, sde_blueprint.get("product_type_id"))
    product_quantity = cast(int, sde_blueprint.get("product_quantity", 1))

    price_type_ids = {m["type_id"] for m in materials}
    if product_type_id is not None:
        price_type_ids.add(product_type_id)
    prices = await market_prices.list_market_prices(db, price_type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    cost_per_run = sum(
        material["quantity"] * market_prices.unit_price(price_by_type_id.get(material["type_id"]))
        for material in materials
    )
    price_figures = f"""
      <div>
        <div class="figure">{format_isk(cost_per_run)}</div>
        <div class="label">Cost / run</div>
      </div>
    """

    product_name = ""
    if product_type_id is not None:
        product_type_docs = await sde.type_docs(db, redis, settings, {product_type_id})
        product_name = str(product_type_docs.get(product_type_id, {}).get("name", ""))
        output_per_run = product_quantity * market_prices.unit_price(
            price_by_type_id.get(product_type_id)
        )
        price_figures += f"""
          <div>
            <div class="figure">{format_isk(output_per_run)}</div>
            <div class="label">Output / run</div>
          </div>
          <div>
            <div class="figure">{format_isk(output_per_run - cost_per_run)}</div>
            <div class="label">Profit / run</div>
          </div>
        """

    produced_text = (
        f"&middot; Produces {escape(product_name)} &times;{product_quantity}"
        if product_name
        else ""
    )
    header = f"""
      <div class="header">
        <img class="icon" src="{blueprint_icon_url}" alt="{blueprint_name}"
          onerror="this.style.visibility='hidden'">
        <div>
          <div class="name">{blueprint_name}</div>
          <div class="meta">{_tech_level_label(is_reaction, is_t2)} {produced_text}</div>
        </div>
      </div>
    """

    material_type_ids = {m["type_id"] for m in materials}
    material_docs = await sde.type_docs(db, redis, settings, material_type_ids)

    def _material_name(type_id: int) -> str:
        return str(material_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    rows = "".join(f"""
          <tr>
            <td>{escape(_material_name(material["type_id"]))}</td>
            <td>{material["quantity"]}</td>
          </tr>
        """ for material in materials)

    body = f"""<div class="page">{header}
      <div class="summary">{price_figures}</div>
      <table>
        <thead><tr><th>Material</th><th>Quantity / run</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <a class="btn btn-secondary back" href="/blueprints/catalog">Back to search</a>
    </div>"""
    return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))


@router.get("/{item_id}", response_class=HTMLResponse)
async def blueprint_detail(
    item_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    blueprints, _ = await character_data.get_merged_blueprints(db, redis, settings, character)
    blueprint = next((bp for bp in blueprints if bp.item_id == item_id), None)
    if blueprint is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Blueprint not found")

    assets, _ = await character_data.get_merged_assets(db, redis, settings, character)
    assets_by_item_id = {asset.item_id: asset for asset in assets}

    is_copy = blueprint.quantity == -2 or blueprint.runs != -1
    resolved_location_id = _resolve_container_chain(blueprint.location_id, assets_by_item_id)
    location_info = await locations.resolve_location_info(
        db, redis, settings, character.access_token, {resolved_location_id}
    )
    location_label = location_label_html(
        resolved_location_id, location_info.get(resolved_location_id)
    )

    sde_blueprints = await sde.blueprint_docs(db, redis, settings, {blueprint.type_id})
    sde_blueprint = sde_blueprints.get(blueprint.type_id)
    type_docs = await sde.type_docs(db, redis, settings, {blueprint.type_id})
    blueprint_type_name = type_docs.get(blueprint.type_id, {}).get("name")
    blueprint_name = escape(str(blueprint_type_name or f"Type {blueprint.type_id}"))
    blueprint_icon_url = escape(icon_url(blueprint.type_id, is_copy))

    if sde_blueprint is None:
        header = f"""
          <div class="header">
            <img class="icon" src="{blueprint_icon_url}" alt="{blueprint_name}"
              onerror="this.style.visibility='hidden'">
            <div>
              <div class="name">{blueprint_name}</div>
              <div class="meta">ME {blueprint.material_efficiency} / TE {blueprint.time_efficiency}
                &middot; {"Copy" if is_copy else "Original"}
                {f"({blueprint.runs} runs)" if is_copy else ""}</div>
              <div class="meta">{location_label}</div>
            </div>
          </div>
        """
        body = f"""<div class="page">{header}
          <p class="empty">No manufacturing data available for this blueprint.</p>
          <a class="btn btn-secondary back" href="/blueprints">Back to blueprints</a>
        </div>"""
        return HTMLResponse(
            render_page(f"{blueprint_name} - eve-build", body, _DETAIL_STYLE, character=character)
        )

    materials = cast(list[dict[str, int]], sde_blueprint["materials"])
    product_type_id = cast(int | None, sde_blueprint.get("product_type_id"))
    product_quantity = cast(int, sde_blueprint.get("product_quantity", 1))

    price_type_ids = {m["type_id"] for m in materials}
    if product_type_id is not None:
        price_type_ids.add(product_type_id)
    prices = await market_prices.list_market_prices(db, price_type_ids)
    price_by_type_id: dict[int, dict[str, object]] = {cast(int, p["_id"]): p for p in prices}

    cost_per_run = sum(
        _material_quantity_per_run(m["quantity"], blueprint.material_efficiency)
        * market_prices.unit_price(price_by_type_id.get(m["type_id"]))
        for m in materials
    )
    price_figures = f"""
      <div>
        <div class="figure">{format_isk(cost_per_run)}</div>
        <div class="label">Cost / run</div>
      </div>
    """
    if product_type_id is not None:
        output_per_run = product_quantity * market_prices.unit_price(
            price_by_type_id.get(product_type_id)
        )
        price_figures += f"""
          <div>
            <div class="figure">{format_isk(output_per_run)}</div>
            <div class="label">Output / run</div>
          </div>
          <div>
            <div class="figure">{format_isk(output_per_run - cost_per_run)}</div>
            <div class="label">Profit / run</div>
          </div>
        """

    header = f"""
      <div class="header">
        <img class="icon" src="{blueprint_icon_url}" alt="{blueprint_name}"
          onerror="this.style.visibility='hidden'">
        <div>
          <div class="name">{blueprint_name}</div>
          <div class="meta">ME {blueprint.material_efficiency} / TE {blueprint.time_efficiency}
            &middot; {"Copy" if is_copy else "Original"}
            {f"({blueprint.runs} runs)" if is_copy else ""}</div>
          <div class="meta">{location_label}</div>
        </div>
      </div>
    """

    on_site_totals: dict[int, int] = {}
    global_totals: dict[int, int] = {}
    for asset in assets:
        global_totals[asset.type_id] = global_totals.get(asset.type_id, 0) + asset.quantity
        if asset.location_id == blueprint.location_id:
            on_site_totals[asset.type_id] = on_site_totals.get(asset.type_id, 0) + asset.quantity

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
        {price_figures}
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
        render_page(f"{blueprint_name} - eve-build", body, _DETAIL_STYLE, character=character)
    )
