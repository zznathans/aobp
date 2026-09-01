from datetime import UTC, datetime
from html import escape
from typing import cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import character_data, locations, sde
from app.services.esi import ColonyRecord
from app.web import format_number, humanize_relative_time, render_page

router = APIRouter(prefix="/pi", tags=["pi"])

_PI_SCOPE = "esi-planets.manage_planets.v1"

_LIST_STYLE = """
  .page { max-width: 60rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  .pi-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .pi-table th, .pi-table td {
    padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2e37; text-align: left;
    vertical-align: middle;
  }
  .pi-table th {
    color: #9aa4b2; font-weight: 600; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.03em;
  }
  .pi-table tr:hover td { background: #1a1d24; }
  .pi-link {
    display: flex; align-items: center; gap: 0.6rem; text-decoration: none; color: inherit;
  }
  .pi-link .icon { width: 32px; height: 32px; border-radius: 4px; flex-shrink: 0; }
  .pi-link .name { font-weight: 600; }
  .status-extracting { color: #3ddc84; }
  .status-idle { color: #9aa4b2; }
  .empty { color: #9aa4b2; }
  .scope-notice {
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px;
    padding: 1rem 1.25rem; color: #9aa4b2;
  }
"""

_DETAIL_STYLE = """
  .page { max-width: 64rem; margin: 0 auto; padding: 2rem 1.5rem; }
  .header { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
  .header .name { font-size: 1.3rem; font-weight: 600; }
  .header .meta { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  h2 { font-size: 1rem; margin: 0 0 0.75rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #2a2e37; }
  .material-cell { display: flex; align-items: center; gap: 0.5rem; }
  .material-cell .icon { width: 24px; height: 24px; border-radius: 4px; flex-shrink: 0; }
  .back { display: inline-block; margin-top: 1.5rem; }
  .empty { color: #9aa4b2; }
  .summary {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
    gap: 0.75rem; margin-bottom: 1.5rem;
  }
  .summary-stat {
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 0.75rem 1rem;
  }
  .summary-stat .value { font-size: 1.2rem; font-weight: 600; }
  .summary-stat .label {
    color: #9aa4b2; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em;
  }
  .status-extracting { color: #3ddc84; }
  .status-idle { color: #9aa4b2; }
  .section-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr));
    gap: 1rem;
  }
  .section-box {
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px;
    padding: 1rem; overflow-x: auto;
  }
"""

_PLANET_TYPE_LABELS: dict[str, str] = {
    "temperate": "Temperate",
    "barren": "Barren",
    "oceanic": "Oceanic",
    "ice": "Ice",
    "gas": "Gas",
    "lava": "Lava",
    "storm": "Storm",
    "plasma": "Plasma",
}

_scope_notice_html = """<div class="page">
  <h1>PI Setups</h1>
  <div class="scope-notice">
    PI Setups needs an extra permission this character hasn't granted yet.
    <a href="/auth/logout">Log out</a> and log back in to grant access.
  </div>
</div>"""


def _planet_type_label(planet_type: str) -> str:
    return _PLANET_TYPE_LABELS.get(planet_type, planet_type.capitalize())


def _parse_esi_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _get_colonies_or_none(
    db: AsyncIOMotorDatabase,
    redis: Redis | None,
    settings: Settings,
    character: CharacterDocument,
) -> list[ColonyRecord] | None:
    """None means this character's session doesn't carry the PI scope (either it was
    never granted, or ESI itself rejected the call with a 401/403) - callers should
    show the re-login notice rather than an empty colony list."""
    if _PI_SCOPE not in character.scopes:
        return None
    try:
        return await character_data.get_character_colonies(
            db, redis, settings, character.access_token, character.character_id
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (401, 403):
            return None
        raise


@router.get("", response_class=HTMLResponse)
async def list_colonies(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    colonies = await _get_colonies_or_none(db, redis, settings, character)
    if colonies is None:
        return HTMLResponse(
            render_page(
                "PI Setups - eve-build", _scope_notice_html, _LIST_STYLE, character=character
            )
        )

    if not colonies:
        body = (
            '<div class="page"><h1>PI Setups</h1>'
            '<p class="empty">No planetary colonies found.</p></div>'
        )
        return HTMLResponse(
            render_page("PI Setups - eve-build", body, _LIST_STYLE, character=character)
        )

    planet_names = await locations.resolve_planet_names(
        db, redis, settings, {colony.planet_id for colony in colonies}
    )
    system_names = await locations.resolve_system_names(
        db, redis, settings, {colony.solar_system_id for colony in colonies}
    )

    rows_html = []
    for colony in sorted(colonies, key=lambda c: planet_names.get(c.planet_id) or ""):
        planet_name = escape(planet_names.get(colony.planet_id) or f"Planet {colony.planet_id}")
        system_name = escape(
            system_names.get(colony.solar_system_id) or f"System {colony.solar_system_id}"
        )
        type_label = escape(_planet_type_label(colony.planet_type))

        now = datetime.now(UTC)
        expiry_times = [
            _parse_esi_time(pin["expiry_time"])
            for pin in colony.pins
            if pin.get("expiry_time") is not None
        ]
        future_expiries = [t for t in expiry_times if t > now]
        if future_expiries:
            soonest = min(future_expiries)
            status_html = (
                f'<span class="status-extracting">Extracting &middot; '
                f"ready {escape(humanize_relative_time(soonest))}</span>"
            )
        elif expiry_times:
            status_html = '<span class="status-idle">Idle &middot; extraction expired</span>'
        else:
            status_html = '<span class="status-idle">Idle</span>'

        detail_href = escape(f"/pi/{colony.planet_id}")
        rows_html.append(f"""
          <tr>
            <td>
              <a class="pi-link" href="{detail_href}">
                <div>
                  <div class="name">{planet_name}</div>
                </div>
              </a>
            </td>
            <td>{type_label}</td>
            <td>{system_name}</td>
            <td>{colony.upgrade_level}</td>
            <td>{colony.num_pins}</td>
            <td>{status_html}</td>
          </tr>
        """)

    body = f"""<div class="page">
      <h1>PI Setups</h1>
      <table class="pi-table">
        <thead>
          <tr>
            <th>Planet</th><th>Type</th><th>System</th>
            <th>Upgrade level</th><th>Pins</th><th>Status</th>
          </tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>"""
    return HTMLResponse(
        render_page("PI Setups - eve-build", body, _LIST_STYLE, character=character)
    )


@router.get("/{planet_id}", response_class=HTMLResponse)
async def colony_detail(
    planet_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    colonies = await _get_colonies_or_none(db, redis, settings, character)
    if colonies is None:
        return HTMLResponse(
            render_page(
                "PI Setups - eve-build", _scope_notice_html, _LIST_STYLE, character=character
            )
        )

    colony = next((c for c in colonies if c.planet_id == planet_id), None)
    if colony is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Colony not found")

    planet_names = await locations.resolve_planet_names(db, redis, settings, {colony.planet_id})
    system_names = await locations.resolve_system_names(
        db, redis, settings, {colony.solar_system_id}
    )
    planet_name = escape(planet_names.get(colony.planet_id) or f"Planet {colony.planet_id}")
    system_name = escape(
        system_names.get(colony.solar_system_id) or f"System {colony.solar_system_id}"
    )
    type_label = escape(_planet_type_label(colony.planet_type))

    schematics = await sde.list_all_planet_schematics(db)
    schematic_by_id = {schematic["_id"]: schematic for schematic in schematics}

    pin_type_ids = {cast(int, pin["type_id"]) for pin in colony.pins}
    schematic_product_type_ids = {
        cast(dict[str, int], s["output"])["type_id"]
        for s in schematic_by_id.values()
        if s["_id"] in {pin.get("schematic_id") for pin in colony.pins}
    }
    schematic_input_type_ids = {
        material["type_id"]
        for s in schematic_by_id.values()
        if s["_id"] in {pin.get("schematic_id") for pin in colony.pins}
        for material in cast(list[dict[str, int]], s["inputs"])
    }
    extractor_product_type_ids = {
        pin["extractor_details"]["product_type_id"]
        for pin in colony.pins
        if pin.get("extractor_details") is not None
        and pin["extractor_details"].get("product_type_id") is not None
    }
    contents_type_ids = {
        item["type_id"] for pin in colony.pins for item in (pin.get("contents") or [])
    }
    route_type_ids = {route["content_type_id"] for route in colony.routes}
    type_ids = (
        pin_type_ids
        | schematic_product_type_ids
        | schematic_input_type_ids
        | extractor_product_type_ids
        | contents_type_ids
        | route_type_ids
    )
    type_docs = await sde.type_docs(db, redis, settings, type_ids)

    def _type_name(type_id: int) -> str:
        return str(type_docs.get(type_id, {}).get("name", f"Type {type_id}"))

    now = datetime.now(UTC)
    extractor_rows = []
    factory_rows = []
    storage_rows = []
    for pin in colony.pins:
        pin_type_name = escape(_type_name(pin["type_id"]))
        extractor_details = pin.get("extractor_details")
        schematic_id = pin.get("schematic_id")

        if extractor_details is not None:
            product_type_id = extractor_details.get("product_type_id")
            product_name = escape(_type_name(product_type_id)) if product_type_id else "-"
            expiry_time = pin.get("expiry_time")
            if expiry_time is not None:
                expiry_dt = _parse_esi_time(expiry_time)
                expiry_label = (
                    escape(humanize_relative_time(expiry_dt)) if expiry_dt > now else "expired"
                )
            else:
                expiry_label = "-"
            extractor_rows.append(f"""
              <tr>
                <td>{pin_type_name}</td>
                <td>{product_name}</td>
                <td>{expiry_label}</td>
              </tr>
            """)
        elif schematic_id is not None and schematic_id in schematic_by_id:
            schematic = schematic_by_id[schematic_id]
            output = cast(dict[str, int], schematic["output"])
            inputs = cast(list[dict[str, int]], schematic["inputs"])
            inputs_text = ", ".join(
                f"{_type_name(material['type_id'])} &times;{material['quantity']}"
                for material in inputs
            )
            output_name = escape(_type_name(output["type_id"]))
            factory_rows.append(f"""
              <tr>
                <td>{pin_type_name}</td>
                <td>{escape(inputs_text)}</td>
                <td>{output_name} &times;{output['quantity']}</td>
              </tr>
            """)
        else:
            contents = pin.get("contents") or []
            contents_text = ", ".join(
                f"{_type_name(item['type_id'])} &times;{format_number(item['amount'])}"
                for item in contents
            )
            storage_rows.append(f"""
              <tr>
                <td>{pin_type_name}</td>
                <td>{escape(contents_text) if contents_text else "-"}</td>
              </tr>
            """)

    link_rows = "".join(f"""
          <tr>
            <td>{link['source_pin_id']}</td>
            <td>{link['destination_pin_id']}</td>
            <td>{link['link_level']}</td>
          </tr>
        """ for link in colony.links)

    route_rows = "".join(f"""
          <tr>
            <td>{route['source_pin_id']}</td>
            <td>{route['destination_pin_id']}</td>
            <td>{escape(_type_name(route['content_type_id']))}
              &times;{format_number(route['quantity'])}</td>
          </tr>
        """ for route in colony.routes)

    def _section(title: str, headers: list[str], rows_html: str) -> str:
        if not rows_html:
            return ""
        header_html = "".join(f"<th>{escape(h)}</th>" for h in headers)
        return f"""
          <div class="section-box">
            <h2>{escape(title)}</h2>
            <table>
              <thead><tr>{header_html}</tr></thead>
              <tbody>{rows_html}</tbody>
            </table>
          </div>
        """

    expiry_times = [
        _parse_esi_time(pin["expiry_time"]) for pin in colony.pins if pin.get("expiry_time")
    ]
    future_expiries = [t for t in expiry_times if t > now]
    if future_expiries:
        status_html = (
            f'<span class="status-extracting">Extracting &middot; '
            f"ready {escape(humanize_relative_time(min(future_expiries)))}</span>"
        )
    elif expiry_times:
        status_html = '<span class="status-idle">Extraction expired</span>'
    else:
        status_html = '<span class="status-idle">Idle</span>'

    header = f"""
      <div class="header">
        <div>
          <div class="name">{planet_name}</div>
          <div class="meta">{type_label} &middot; {system_name} &middot;
            Upgrade level {colony.upgrade_level} &middot; {colony.num_pins} pins</div>
        </div>
      </div>
    """

    summary_html = f"""
      <div class="summary">
        <div class="summary-stat">
          <div class="value">{len(extractor_rows)}</div>
          <div class="label">Extractors</div>
        </div>
        <div class="summary-stat">
          <div class="value">{len(factory_rows)}</div>
          <div class="label">Factories</div>
        </div>
        <div class="summary-stat">
          <div class="value">{len(storage_rows)}</div>
          <div class="label">Storage</div>
        </div>
        <div class="summary-stat">
          <div class="value">{status_html}</div>
          <div class="label">Status</div>
        </div>
      </div>
    """

    body = f"""<div class="page">{header}
      {summary_html}
      <div class="section-grid">
        {_section("Extractors", ["Pin", "Product", "Expires"], "".join(extractor_rows))}
        {_section("Factories", ["Pin", "Inputs", "Output"], "".join(factory_rows))}
        {_section("Storage", ["Pin", "Contents"], "".join(storage_rows))}
        {_section("Links", ["Source pin", "Destination pin", "Link level"], link_rows)}
        {_section("Routes", ["Source pin", "Destination pin", "Content"], route_rows)}
      </div>
      <a class="btn btn-secondary back" href="/pi">Back to PI Setups</a>
    </div>"""
    page_title = f"{planet_names.get(colony.planet_id) or planet_name} - eve-build"
    return HTMLResponse(render_page(page_title, body, _DETAIL_STYLE, character=character))
