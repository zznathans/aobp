from html import escape
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import character_data, plan, sde
from app.services.locations import resolve_container_chain
from app.web import (
    format_duration,
    format_isk,
    item_icon_url,
    item_line_html,
    render_page,
    section_html,
    summary_stat_html,
)

router = APIRouter(prefix="/plans", tags=["plans"])

_LIST_STYLE = ["/static/card.css", "/static/plans-list.css"]
_DETAIL_STYLE = ["/static/card.css", "/static/plans-detail.css"]


def _plan_url(plan_id: str) -> str:
    safe_plan_id = quote(plan_id, safe="")
    return f"/plans/{safe_plan_id}"


@router.get("", response_class=HTMLResponse)
async def list_plans(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> HTMLResponse:
    plans = await plan.list_plans(db, character.character_id)

    new_link = '<a class="btn btn-primary" href="/plans/new">New plan</a>'

    if not plans:
        body = f"""<div class="page">
          <h1>Plans</h1>
          {new_link}
          <p class="empty">No saved plans yet.</p>
        </div>"""
        return HTMLResponse(render_page("Plans", body, _LIST_STYLE, character=character))

    cards = "".join(f"""
          <a class="item-card" href="{escape(_plan_url(doc.id))}">
            <div class="item-card-content">
              <div class="item-title">{escape(doc.name)}</div>
              {item_line_html("Blueprints", str(len(doc.lines)))}
              {item_line_html("Updated", doc.updated_at.strftime("%Y-%m-%d %H:%M"))}
            </div>
          </a>
        """ for doc in plans)
    body = f"""<div class="page">
      <h1>Plans</h1>
      {new_link}
      <div class="item-grid">{cards}</div>
    </div>"""
    return HTMLResponse(render_page("Plans", body, _LIST_STYLE, character=character))


@router.get("/new", response_class=HTMLResponse)
async def new_plan_picker(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    q: str = Query(default=""),
) -> HTMLResponse:
    query = q.strip()

    search_form = f"""
      <form method="get" class="filters">
        <input type="text" name="q" value="{escape(query)}"
          placeholder="Search your blueprints and the catalog by name" autofocus>
        <button type="submit" class="btn btn-secondary">Search</button>
      </form>
    """

    if len(query) < 2:
        rows_html = (
            '<p class="empty">Search above to add owned or catalog blueprints to the plan.</p>'
        )
        if query:
            rows_html = '<p class="empty">Keep typing - search needs at least 2 characters.</p>'
        body = f"""<div class="page">
          <h1>New plan</h1>
          {search_form}
          <form method="post" action="/plans" class="picker-form">
            <input type="text" name="name" placeholder="Plan name" required
              class="plan-name-input">
            {rows_html}
            <button type="submit" class="btn btn-primary">Create plan</button>
          </form>
        </div>"""
        return HTMLResponse(render_page("New plan", body, _LIST_STYLE, character=character))

    # Only render rows matching the search - listing every owned blueprint unconditionally
    # can produce thousands of hidden form fields for characters with large collections,
    # exceeding Starlette's per-request form field cap.
    owned_blueprints, _ = await character_data.get_merged_blueprints(db, redis, settings, character)
    assets, _ = await character_data.get_merged_assets(db, redis, settings, character)
    assets_by_item_id = {asset.item_id: asset for asset in assets}
    type_docs = await sde.type_docs(db, redis, settings, {bp.type_id for bp in owned_blueprints})

    query_lower = query.lower()
    matched_owned = []
    for bp in owned_blueprints:
        name = str(type_docs.get(bp.type_id, {}).get("name", f"Type {bp.type_id}"))
        if query_lower not in name.lower():
            continue
        matched_owned.append((bp, name))
        if len(matched_owned) >= 50:
            break

    sde_blueprints_for_owned = await sde.blueprint_docs(
        db, redis, settings, {bp.type_id for bp, _ in matched_owned}
    )

    seen_type_ids: set[int] = set()
    rows = []
    for bp, name in matched_owned:
        seen_type_ids.add(bp.type_id)
        product_type_id = sde_blueprints_for_owned.get(bp.type_id, {}).get("product_type_id")
        location_id = resolve_container_chain(bp.location_id, assets_by_item_id)
        row_id = f"o{bp.item_id}"
        rows.append(
            _picker_row_html(
                row_id=row_id,
                type_id=bp.type_id,
                icon_type_id=cast(int | None, product_type_id) or bp.type_id,
                name=name,
                default_runs=bp.runs if bp.runs != -1 else 1,
                default_me=bp.material_efficiency,
                source_item_id=bp.item_id,
                location_id=location_id,
            )
        )

    catalog_docs = await sde.search_blueprints_by_name(db, query)
    for doc in catalog_docs:
        type_id = cast(int, doc["_id"])
        if type_id in seen_type_ids:
            continue
        row_id = f"c{type_id}"
        rows.append(
            _picker_row_html(
                row_id=row_id,
                type_id=type_id,
                icon_type_id=cast(int | None, doc.get("product_type_id")) or type_id,
                name=str(doc["name"]),
                default_runs=1,
                default_me=0,
                source_item_id=None,
                location_id=None,
            )
        )

    if not rows:
        rows_html = '<p class="empty">No blueprints match your search.</p>'
    else:
        rows_html = f'<div class="item-grid">{"".join(rows)}</div>'

    body = f"""<div class="page">
      <h1>New plan</h1>
      {search_form}
      <form method="post" action="/plans" class="picker-form">
        <input type="text" name="name" placeholder="Plan name" required class="plan-name-input">
        {rows_html}
        <button type="submit" class="btn btn-primary">Create plan</button>
      </form>
    </div>"""
    return HTMLResponse(render_page("New plan", body, _LIST_STYLE, character=character))


def _picker_row_html(
    *,
    row_id: str,
    type_id: int,
    icon_type_id: int,
    name: str,
    default_runs: int,
    default_me: int,
    source_item_id: int | None,
    location_id: int | None,
) -> str:
    icon = escape(item_icon_url(icon_type_id))
    escaped_name = escape(name)
    return f"""
      <div class="item-card picker-row">
        <img class="item-card-center-icon" src="{icon}" alt="" aria-hidden="true"
          onerror="this.style.visibility='hidden'">
        <div class="item-card-content">
          <label class="item-title">
            <input type="checkbox" name="include__{row_id}" value="1">
            {escaped_name}
          </label>
          <input type="hidden" name="type_id__{row_id}" value="{type_id}">
          <input type="hidden" name="source_item_id__{row_id}"
            value="{source_item_id if source_item_id is not None else ""}">
          <input type="hidden" name="location_id__{row_id}"
            value="{location_id if location_id is not None else ""}">
          <label class="item-line">
            <span>Runs</span>
            <input type="number" name="runs__{row_id}" value="{default_runs}" min="1"
              class="item-value">
          </label>
          <label class="item-line">
            <span>ME</span>
            <input type="number" name="me__{row_id}" value="{default_me}" min="0" max="10"
              class="item-value">
          </label>
        </div>
      </div>
    """


@router.post("")
async def create_plan(
    request: Request,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RedirectResponse:
    form = await request.form()
    name = str(form.get("name", "")).strip() or "Untitled plan"

    row_ids = {key[len("include__") :] for key in form if key.startswith("include__")}
    lines = [
        plan.PlanLineInput(
            type_id=int(cast(str, form[f"type_id__{row_id}"])),
            runs=max(1, int(cast(str, form.get(f"runs__{row_id}", 1)) or 1)),
            material_efficiency=max(0, min(10, int(cast(str, form.get(f"me__{row_id}", 0)) or 0))),
            source_item_id=(
                int(cast(str, source_item_id))
                if (source_item_id := form.get(f"source_item_id__{row_id}"))
                else None
            ),
            location_id=(
                int(cast(str, location_id))
                if (location_id := form.get(f"location_id__{row_id}"))
                else None
            ),
        )
        for row_id in row_ids
    ]

    doc = await plan.create_plan(db, character.character_id, name, lines)
    return RedirectResponse(_plan_url(doc.id), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{plan_id}", response_class=HTMLResponse)
async def plan_detail(
    plan_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    doc = await plan.get_plan(db, plan_id, character.character_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")

    summary = await plan.compute_plan_summary(db, redis, settings, character, doc)

    stats = (
        summary_stat_html(format_isk(summary.total_cost), "Total cost")
        + summary_stat_html(format_isk(summary.total_output), "Total output")
        + summary_stat_html(format_isk(summary.total_profit), "Total profit")
        + summary_stat_html(format_duration(summary.total_time_seconds), "Total job time")
    )

    aggregated_cards = "".join(f"""
          <div class="item-card">
            <img class="item-card-center-icon" src="{escape(item_icon_url(material.type_id))}"
              alt="" aria-hidden="true" onerror="this.style.visibility='hidden'">
            <div class="item-card-content">
              <div class="item-title">{escape(material.name)}</div>
              {item_line_html("Needed", str(material.needed))}
              {item_line_html("Have", str(material.global_have))}
              {
                item_line_html(
                    "Missing", f'<span class="short">{material.global_missing}</span>'
                )
                if material.global_missing
                else item_line_html("Missing", "0")
            }
            </div>
          </div>
        """ for material in summary.aggregated_materials)
    aggregated_section = section_html("Aggregated materials", aggregated_cards)

    line_cards = "".join(_line_card_html(doc.id, line_summary) for line_summary in summary.lines)
    lines_section = section_html("Blueprints in this plan", line_cards)

    add_form = f"""
      <form method="get" action="/plans/{escape(doc.id)}/lines/new" class="filters">
        <button type="submit" class="btn btn-secondary">Add a blueprint</button>
      </form>
    """

    delete_form = f"""
      <form method="post" action="/plans/{escape(doc.id)}/delete"
        onsubmit="return confirm('Delete this plan?')">
        <button type="submit" class="btn btn-danger">Delete plan</button>
      </form>
    """

    rename_form = f"""
      <form method="post" action="/plans/{escape(doc.id)}/rename" class="filters">
        <input type="text" name="name" value="{escape(doc.name)}" required
          class="plan-name-input">
        <button type="submit" class="btn btn-secondary">Rename</button>
      </form>
    """

    header = f"""
      <div class="header">
        <div>
          <div class="name">{escape(doc.name)}</div>
          <div class="meta">{len(doc.lines)} blueprint(s)</div>
        </div>
      </div>
      {rename_form}
    """

    body = f"""<div class="page">{header}
      <div class="summary">{stats}</div>
      {add_form}
      <div class="section-grid">
        {aggregated_section}
        {lines_section}
      </div>
      {delete_form}
      <a class="btn btn-secondary back" href="/plans">Back to plans</a>
    </div>"""
    return HTMLResponse(
        render_page(f"{doc.name} - eve-build", body, _DETAIL_STYLE, character=character)
    )


def _line_card_html(plan_id: str, line_summary: plan.LineSummary) -> str:
    line = line_summary.line
    if not line_summary.has_manufacturing_data:
        body = '<p class="empty">No manufacturing data available for this blueprint.</p>'
    else:
        stats = (
            item_line_html("Runs", str(line.runs))
            + item_line_html("ME", str(line.material_efficiency))
            + item_line_html("Cost", format_isk(line_summary.cost))
            + item_line_html("Output", format_isk(line_summary.output))
            + item_line_html("Profit", format_isk(line_summary.profit))
            + item_line_html("Buildable (assets)", str(line_summary.global_buildable))
        )
        body = stats

    edit_form = f"""
      <div class="line-actions">
        <form method="post" action="/plans/{escape(plan_id)}/lines/{escape(line.line_id)}"
          class="line-edit-form">
          <input type="number" name="runs" value="{line.runs}" min="1" class="item-value">
          <input type="number" name="material_efficiency" value="{line.material_efficiency}"
            min="0" max="10" class="item-value">
          <button type="submit" class="btn btn-secondary">Update</button>
        </form>
        <form method="post" action="/plans/{escape(plan_id)}/lines/{escape(line.line_id)}/delete">
          <button type="submit" class="btn btn-danger">Remove</button>
        </form>
      </div>
    """

    icon_type_id = line_summary.product_type_id or line.type_id
    return f"""
      <div class="item-card">
        <img class="item-card-center-icon"
          src="{escape(item_icon_url(icon_type_id))}" alt="" aria-hidden="true"
          onerror="this.style.visibility='hidden'">
        <div class="item-card-content">
          <div class="item-title">{escape(line_summary.blueprint_name)}</div>
          {body}
          {edit_form}
        </div>
      </div>
    """


@router.get("/{plan_id}/lines/new", response_class=HTMLResponse)
async def add_line_picker(
    plan_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    q: str = Query(default=""),
) -> HTMLResponse:
    doc = await plan.get_plan(db, plan_id, character.character_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")

    query = q.strip()
    results_html = ""
    if len(query) >= 2:
        catalog_docs = await sde.search_blueprints_by_name(db, query)
        if not catalog_docs:
            results_html = '<p class="empty">No blueprints match your search.</p>'
        else:
            cards = "".join(f"""
                  <form method="post" action="/plans/{escape(plan_id)}/lines" class="item-card">
                    <img class="item-card-center-icon"
                      src="{
                        escape(
                            item_icon_url(
                                cast(int, result.get("product_type_id") or result["_id"])
                            )
                        )
                    }" alt="" aria-hidden="true" onerror="this.style.visibility='hidden'">
                    <div class="item-card-content">
                      <div class="item-title">{escape(str(result["name"]))}</div>
                      <input type="hidden" name="type_id" value="{result["_id"]}">
                      <label class="item-line">
                        <span>Runs</span>
                        <input type="number" name="runs" value="1" min="1" class="item-value">
                      </label>
                      <label class="item-line">
                        <span>ME</span>
                        <input type="number" name="material_efficiency" value="0" min="0"
                          max="10" class="item-value">
                      </label>
                      <button type="submit" class="btn btn-primary">Add to plan</button>
                    </div>
                  </form>
                """ for result in catalog_docs)
            results_html = f'<div class="item-grid">{cards}</div>'
    elif query:
        results_html = '<p class="empty">Keep typing - search needs at least 2 characters.</p>'

    search_form = f"""
      <form method="get" class="filters">
        <input type="text" name="q" value="{escape(query)}"
          placeholder="Search all blueprints by name" autofocus>
        <button type="submit" class="btn btn-secondary">Search</button>
      </form>
    """

    body = f"""<div class="page">
      <h1>Add a blueprint to {escape(doc.name)}</h1>
      {search_form}
      {results_html}
      <a class="btn btn-secondary back" href="{escape(_plan_url(plan_id))}">Back to plan</a>
    </div>"""
    return HTMLResponse(render_page("Add blueprint", body, _LIST_STYLE, character=character))


@router.post("/{plan_id}/lines")
async def add_line(
    plan_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    type_id: int = Form(...),
    runs: int = Form(1),
    material_efficiency: int = Form(0),
) -> RedirectResponse:
    updated = await plan.add_line(
        db,
        plan_id,
        character.character_id,
        plan.PlanLineInput(
            type_id=type_id,
            runs=max(1, runs),
            material_efficiency=max(0, min(10, material_efficiency)),
        ),
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return RedirectResponse(_plan_url(plan_id), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{plan_id}/lines/{line_id}")
async def update_line(
    plan_id: str,
    line_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    runs: int = Form(1),
    material_efficiency: int = Form(0),
) -> RedirectResponse:
    updated = await plan.update_line(
        db,
        plan_id,
        character.character_id,
        line_id,
        max(1, runs),
        max(0, min(10, material_efficiency)),
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return RedirectResponse(_plan_url(plan_id), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{plan_id}/lines/{line_id}/delete")
async def delete_line(
    plan_id: str,
    line_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RedirectResponse:
    updated = await plan.remove_line(db, plan_id, character.character_id, line_id)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return RedirectResponse(_plan_url(plan_id), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{plan_id}/rename")
async def rename_plan(
    plan_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    name: str = Form(...),
) -> RedirectResponse:
    updated = await plan.rename_plan(
        db, plan_id, character.character_id, name.strip() or "Untitled plan"
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return RedirectResponse(_plan_url(plan_id), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{plan_id}/delete")
async def delete_plan(
    plan_id: str,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RedirectResponse:
    deleted = await plan.delete_plan(db, plan_id, character.character_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return RedirectResponse("/plans", status_code=status.HTTP_303_SEE_OTHER)
