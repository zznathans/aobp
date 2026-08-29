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
from app.services import character_data, esi
from app.web import render_page

router = APIRouter(prefix="/settings", tags=["settings"])

_STYLE = """
  .page { max-width: 36rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  h2 { font-size: 1.05rem; margin: 1.5rem 0 0.75rem; }
  .card {
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 1.25rem;
  }
  .card p { color: #9aa4b2; font-size: 0.9rem; margin: 0 0 1rem; }
  .status-list { margin: 0; padding: 0; list-style: none; }
  .status-list li {
    display: flex; justify-content: space-between; padding: 0.5rem 0;
    border-bottom: 1px solid #2a2e37; font-size: 0.9rem;
  }
  .status-list li:last-child { border-bottom: none; }
  .status-ok { color: #3ddc84; }
  .status-missing { color: #f0625a; }
  .actions { margin-top: 1.25rem; display: flex; gap: 0.75rem; }
"""

_STATUS_SOURCES = (
    ("Assets", character_data.get_corporation_assets, "requires the Director role"),
    ("Blueprints", character_data.get_corporation_blueprints, "requires the Director role"),
    (
        "Industry jobs",
        character_data.get_corporation_industry_jobs,
        "requires the Director or Factory_Manager role",
    ),
)


@router.get("", response_class=HTMLResponse)
async def show_settings(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    if not character_data.corp_data_connected(character):
        body = """<div class="page">
          <h1>Settings</h1>
          <div class="card">
            <h2>Corporation data</h2>
            <p>
              Optionally pull your corporation's assets, blueprints, and industry jobs
              into eve-build alongside your personal ones, so materials and jobs sitting
              in corp hangars show up in readiness/buildable calculations too. Corp
              assets and blueprints require you to hold the Director role in your
              corporation; corp industry jobs allows Director or Factory_Manager.
            </p>
            <div class="actions">
              <a class="btn btn-primary" href="/auth/connect-corp">Connect corporation data</a>
            </div>
          </div>
        </div>"""
        return HTMLResponse(render_page("Settings", body, _STYLE, character=character))

    corporation_id = cast(int, character.corporation_id)
    corp_access_token = cast(str, character.corp_access_token)
    corporation_name = await esi.get_corporation_name(settings, corporation_id)
    corp_label = escape(corporation_name or f"Corporation {corporation_id}")

    status_rows = ""
    for label, fetch, required_role in _STATUS_SOURCES:
        result = await fetch(db, redis, settings, corp_access_token, corporation_id)
        if result is None:
            role_text = escape(required_role)
            status_html = f'<span class="status-missing">No permission &mdash; {role_text}</span>'
        else:
            status_html = f'<span class="status-ok">Connected &middot; {len(result)} found</span>'
        status_rows += f"<li><span>{escape(label)}</span>{status_html}</li>"

    body = f"""<div class="page">
      <h1>Settings</h1>
      <div class="card">
        <h2>Corporation data</h2>
        <p>Connected to <strong>{corp_label}</strong>.</p>
        <ul class="status-list">{status_rows}</ul>
        <div class="actions">
          <a class="btn btn-secondary" href="/auth/disconnect-corp">Disconnect</a>
        </div>
      </div>
    </div>"""
    return HTMLResponse(render_page("Settings", body, _STYLE, character=character))
