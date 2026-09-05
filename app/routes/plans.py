from datetime import UTC, datetime
from html import escape
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.routes.build import render_build_resolution_sections
from app.services import build_chain, plan, sde
from app.web import format_isk, item_icon_url, render_page, summary_stat_html

router = APIRouter(prefix="/plans", tags=["plans"])

_LIST_STYLE = ["/static/card.css", "/static/build.css"]
_DETAIL_STYLE = ["/static/card.css", "/static/build-detail.css"]


def _format_timestamp(value: datetime) -> str:
    return value.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")


@router.get("", response_class=HTMLResponse)
async def list_plans(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    plans = await plan.list_plans(db, character.character_id)

    if not plans:
        body = (
            '<div class="page"><h1>Plans</h1>'
            '<p class="empty">No plans saved yet - build something and add it to a plan.</p></div>'
        )
        return HTMLResponse(render_page("Plans", body, _LIST_STYLE, character=character))

    target_type_ids = {cast(int, doc["target_type_id"]) for doc in plans}
    type_docs = await sde.type_docs(db, redis, settings, target_type_ids)

    def _name(type_id: int) -> str:
        return str(type_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    cards = "".join(f"""
          <a class="item-card" href="/plans/{doc['_id']}">
            <div class="item-card-content">
              <div class="item-title">
                <img class="item-title-icon"
                  src="{escape(item_icon_url(cast(int, doc['target_type_id'])))}"
                  alt="" onerror="this.style.visibility='hidden'">
                {escape(_name(cast(int, doc["target_type_id"])))}
              </div>
              <div class="item-line"><span>Quantity</span>
                <span class="item-value">{doc["target_quantity"]}</span></div>
              <div class="item-line"><span>Created</span>
                <span class="item-value">
                  {_format_timestamp(cast(datetime, doc["created_at"]))}</span></div>
            </div>
          </a>
        """ for doc in plans)

    body = f"""<div class="page">
      <h1>Plans</h1>
      <div class="item-grid">{cards}</div>
    </div>"""
    return HTMLResponse(render_page("Plans", body, _LIST_STYLE, character=character))


@router.get("/create")
async def create_plan_from_build(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    type_id: int = Query(...),
    qty: int = Query(default=1, ge=1),
    build: str = Query(default=""),
) -> RedirectResponse:
    build_set = frozenset(int(t) for t in build.split(",") if t.strip().isdigit())
    plan_id = await plan.create_plan(db, character.character_id, type_id, qty, build_set)
    return RedirectResponse(f"/plans/{plan_id}")


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

    type_id = cast(int, doc["target_type_id"])
    qty = cast(int, doc["target_quantity"])
    build_set = frozenset(cast(list[int], doc["build_set"]))

    resolution = await build_chain.resolve_build_chain(db, redis, settings, type_id, qty, build_set)
    item_name = escape(resolution.target_name)
    item_icon = escape(item_icon_url(type_id))
    page_title = f"{item_name} - eve-build"

    header = f"""
      <div class="header">
        <img class="icon" src="{item_icon}" alt="{item_name}"
          onerror="this.style.visibility='hidden'">
        <div>
          <div class="name">{item_name}</div>
          <div class="meta">Plan for {qty} &times; &middot;
            saved {_format_timestamp(cast(datetime, doc["created_at"]))}</div>
        </div>
      </div>
    """

    profit = resolution.output_value - resolution.raw_material_cost
    stats = (
        summary_stat_html(format_isk(resolution.raw_material_cost), "Raw material cost")
        + summary_stat_html(format_isk(resolution.output_value), "Output value")
        + summary_stat_html(format_isk(profit), "Profit")
        + summary_stat_html(str(len(resolution.steps)), "Build steps")
    )

    sections = render_build_resolution_sections(
        resolution, type_id=type_id, qty=qty, build_set=build_set, interactive=False
    )

    body = f"""<div class="page">{header}
      <div class="summary">{stats}</div>
      {sections}
      <a class="btn btn-secondary back" href="/plans">Back to plans</a>
    </div>"""
    return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))
