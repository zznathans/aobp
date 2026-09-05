from html import escape
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character_optional
from app.models.character import CharacterDocument
from app.services import build_chain, sde
from app.web import format_isk, item_icon_url, item_line_html, render_page

router = APIRouter(prefix="/build", tags=["build"])

_CHOOSER_STYLE = ["/static/card.css", "/static/build.css"]
_LIST_STYLE = ["/static/card.css", "/static/build.css"]
_DETAIL_STYLE = ["/static/card.css", "/static/build-detail.css"]


def _summary_stat(value: str, label: str) -> str:
    return f"""
      <div class="summary-stat">
        <div class="value">{value}</div>
        <div class="label">{escape(label)}</div>
      </div>
    """


def _section(title: str, cards_html: str) -> str:
    if not cards_html:
        return ""
    return f"""
      <div class="section-box">
        <h2>{escape(title)}</h2>
        <div class="item-grid">{cards_html}</div>
      </div>
    """


def _build_toggle_href(
    target_type_id: int,
    qty: int,
    build_set: frozenset[int],
    toggled_type_id: int,
    *,
    adding: bool,
) -> str:
    updated = (build_set | {toggled_type_id}) if adding else (build_set - {toggled_type_id})
    query = f"qty={qty}"
    if updated:
        query += f"&build={','.join(str(t) for t in sorted(updated))}"
    return f"/build/items/{target_type_id}?{query}"


@router.get("", response_class=HTMLResponse)
async def build_chooser(
    character: CharacterDocument | None = Depends(get_current_character_optional),
) -> HTMLResponse:
    body = """<div class="page">
      <h1>What do you want to do?</h1>
      <div class="chooser-grid">
        <a class="chooser-card" href="/build/items">
          <div class="chooser-title">I know what I want to build</div>
          <div class="chooser-description">
            Search for an item - we'll work out the blueprint and material chain needed
            to build it, including any sub-components that need building first.
          </div>
        </a>
        <a class="chooser-card" href="/blueprints/catalog">
          <div class="chooser-title">I know which blueprint I want</div>
          <div class="chooser-description">
            Search the blueprint catalog directly and see its materials, cost, and
            output for a single run.
          </div>
        </a>
      </div>
    </div>"""
    return HTMLResponse(render_page("Build", body, _CHOOSER_STYLE, character=character))


@router.get("/items", response_class=HTMLResponse)
async def item_search(
    character: CharacterDocument | None = Depends(get_current_character_optional),
    db: AsyncIOMotorDatabase = Depends(get_database),
    q: str = Query(default=""),
) -> HTMLResponse:
    query = q.strip()

    if len(query) >= 2:
        docs = await sde.search_items_by_name(db, query)
        if not docs:
            results_html = '<p class="empty">No items match your search.</p>'
        else:
            cards = "".join(f"""
                  <a class="item-card" href="/build/items/{doc['_id']}">
                    <div class="item-card-content">
                      <div class="item-title">
                        <img class="item-title-icon"
                          src="{escape(item_icon_url(cast(int, doc['_id'])))}"
                          alt="" onerror="this.style.visibility='hidden'">
                        {escape(str(doc["name"]))}
                      </div>
                    </div>
                  </a>
                """ for doc in docs)
            results_html = f'<div class="item-grid">{cards}</div>'
    elif query:
        results_html = '<p class="empty">Keep typing - search needs at least 2 characters.</p>'
    else:
        results_html = ""

    search_form = f"""
      <form method="get" class="filters">
        <input type="text" name="q" value="{escape(query)}"
          placeholder="Search for an item to build" autofocus>
      </form>
    """
    body = f"""<div class="page">
      <h1>What do you want to build?</h1>
      {search_form}
      {results_html}
    </div>"""
    return HTMLResponse(render_page("Build an item", body, _LIST_STYLE, character=character))


@router.get("/items/{type_id}", response_class=HTMLResponse)
async def item_build_chain(
    type_id: int,
    character: CharacterDocument | None = Depends(get_current_character_optional),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    qty: int = Query(default=1, ge=1),
    build: str = Query(default=""),
) -> HTMLResponse:
    type_docs = await sde.type_docs(db, redis, settings, {type_id})
    type_doc = type_docs.get(type_id)
    if type_doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")

    build_set = frozenset(int(t) for t in build.split(",") if t.strip().isdigit())
    resolution = await build_chain.resolve_build_chain(db, redis, settings, type_id, qty, build_set)
    item_name = escape(resolution.target_name)
    item_icon = escape(item_icon_url(type_id))
    qty_text = escape(str(qty))
    page_title = f"{item_name} - eve-build"

    header = f"""
      <div class="header">
        <img class="icon" src="{item_icon}" alt="{item_name}"
          onerror="this.style.visibility='hidden'">
        <div>
          <div class="name">{item_name}</div>
          <div class="meta">Building {qty_text} &times;</div>
        </div>
      </div>
    """

    if not resolution.is_buildable:
        body = f"""<div class="page">{header}
          <p class="empty">No blueprint or reaction formula produces this item - it can only
            be bought, not built.</p>
          <a class="btn btn-secondary back" href="/build/items">Back to search</a>
        </div>"""
        return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))

    profit = resolution.output_value - resolution.raw_material_cost
    stats = (
        _summary_stat(format_isk(resolution.raw_material_cost), "Raw material cost")
        + _summary_stat(format_isk(resolution.output_value), "Output value")
        + _summary_stat(format_isk(profit), "Profit")
        + _summary_stat(str(len(resolution.steps)), "Build steps")
    )

    def _buy_flag(step_type_id: int) -> str:
        if step_type_id == type_id:
            return ""
        href = escape(_build_toggle_href(type_id, qty, build_set, step_type_id, adding=False))
        return f'<a class="flag flag-buy" href="{href}">Buy instead</a>'

    step_cards = "".join(f"""
          <div class="item-card">
            <div class="item-card-content">
              <div class="item-title">
                <img class="item-title-icon" src="{escape(item_icon_url(step.type_id))}" alt=""
                  onerror="this.style.visibility='hidden'">
                {escape(step.name)}
                {_buy_flag(step.type_id)}
              </div>
              {item_line_html("Runs", str(step.runs))}
              {item_line_html("Produces", str(step.quantity_needed))}
            </div>
          </div>
        """ for step in resolution.steps)
    steps_section = _section("Build steps", step_cards)

    def _material_flag(material: build_chain.RawMaterial) -> str:
        if not material.is_buildable:
            return '<span class="flag flag-buy">Bought</span>'
        href = escape(_build_toggle_href(type_id, qty, build_set, material.type_id, adding=True))
        return f'<a class="flag flag-build" href="{href}">Build</a>'

    raw_cards = "".join(f"""
          <div class="item-card{' item-card-buildable' if material.is_buildable else ''}">
            <div class="item-card-content">
              <div class="item-title">
                <img class="item-title-icon" src="{escape(item_icon_url(material.type_id))}"
                  alt="" onerror="this.style.visibility='hidden'">
                {escape(material.name)}
                {_material_flag(material)}
              </div>
              {item_line_html("Quantity", str(material.quantity))}
              {item_line_html("Est. cost", format_isk(material.quantity * material.unit_price))}
            </div>
          </div>
        """ for material in resolution.raw_materials)
    raw_section = _section("Materials", raw_cards)

    body = f"""<div class="page">{header}
      <div class="summary">{stats}</div>
      {raw_section}
      {steps_section}
      <a class="btn btn-secondary back" href="/build/items">Back to search</a>
    </div>"""
    return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))
