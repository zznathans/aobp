from datetime import UTC, datetime
from html import escape
from typing import cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
  .page { max-width: 40rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
  h2 { font-size: 1.05rem; margin: 0 0 0.75rem; }
  .card {
    background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 1.25rem;
    margin-bottom: 1.5rem;
  }
  .card p { color: #9aa4b2; font-size: 0.9rem; margin: 0 0 1rem; }
  .card.danger { border-color: #f0625a33; }
  .card.danger h2 { color: #f0625a; }
  .kv-list, .status-list { margin: 0; padding: 0; list-style: none; }
  .kv-list li, .status-list li {
    display: flex; justify-content: space-between; gap: 1rem; padding: 0.5rem 0;
    border-bottom: 1px solid #2a2e37; font-size: 0.9rem;
  }
  .kv-list li:last-child, .status-list li:last-child { border-bottom: none; }
  .kv-list dt, .status-list span:first-child { color: #9aa4b2; }
  .kv-list dd { margin: 0; text-align: right; }
  .scopes { font-size: 0.8rem; color: #9aa4b2; word-break: break-word; text-align: right; }
  .status-ok { color: #3ddc84; }
  .status-missing { color: #f0625a; }
  .status-shared { font-size: 0.75rem; color: #9aa4b2; }
  .actions { margin-top: 1.25rem; display: flex; gap: 0.75rem; }
"""

_CORP_STATUS_SOURCES = (
    ("Assets", character_data.get_corporation_assets, "requires the Director role"),
    ("Blueprints", character_data.get_corporation_blueprints, "requires the Director role"),
    (
        "Industry jobs",
        character_data.get_corporation_industry_jobs,
        "requires the Director or Factory_Manager role",
    ),
)


def _format_timestamp(value: datetime) -> str:
    return value.replace(tzinfo=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _render_account_section(character: CharacterDocument) -> str:
    avatar_url = escape(
        f"https://images.evetech.net/characters/{character.character_id}/portrait?size=64"
    )
    scopes_text = escape(", ".join(sorted(character.scopes)) or "none")
    return f"""
      <div class="card">
        <h2>Account</h2>
        <div class="header"
          style="display: flex; gap: 1rem; align-items: center; margin-bottom: 1rem;">
          <img src="{avatar_url}" alt="{escape(character.character_name)}"
            style="width: 48px; height: 48px; border-radius: 8px;">
          <div>
            <div style="font-weight: 600;">{escape(character.character_name)}</div>
            <div style="color: #9aa4b2; font-size: 0.85rem;">
              Character ID {character.character_id}
            </div>
          </div>
        </div>
        <ul class="kv-list">
          <li><span>Login granted</span><dd>{_format_timestamp(character.created_at)}</dd></li>
          <li><span>Last refreshed</span><dd>{_format_timestamp(character.updated_at)}</dd></li>
          <li><span>Login scopes</span><dd class="scopes">{scopes_text}</dd></li>
        </ul>
      </div>
    """


def _render_data_section(sources: list[character_data.CachedDataSource]) -> str:
    rows = ""
    for source in sources:
        last_updated = (
            _format_timestamp(source.cached_at) if source.cached_at else "never fetched yet"
        )
        shared_note = (
            ' <span class="status-shared">(shared with your corp)</span>' if source.shared else ""
        )
        rows += f"""
          <li>
            <span>{escape(source.label)}{shared_note}</span>
            <dd>{source.count} items &middot; {last_updated}</dd>
          </li>
        """
    return f"""
      <div class="card">
        <h2>Data eve-build has stored</h2>
        <p>
          Cached copies of your assets, blueprints, and industry jobs (and your
          corporation's, if connected) so pages load quickly instead of hitting ESI
          every time. Refreshes automatically after an hour, or force it below.
        </p>
        <ul class="kv-list">{rows}</ul>
        <div class="actions">
          <a class="btn btn-secondary" href="/settings/refresh">Force refresh</a>
        </div>
      </div>
    """


def _render_corp_section(corp_label: str | None, status_rows: str) -> str:
    if corp_label is None:
        return """
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
        """
    return f"""
      <div class="card">
        <h2>Corporation data</h2>
        <p>Connected to <strong>{corp_label}</strong>.</p>
        <ul class="status-list">{status_rows}</ul>
        <div class="actions">
          <a class="btn btn-secondary" href="/auth/disconnect-corp">Disconnect</a>
        </div>
      </div>
    """


def _render_danger_section() -> str:
    return """
      <div class="card danger">
        <h2>Clear my data</h2>
        <p>
          Deletes everything eve-build has stored about you - cached assets,
          blueprints, and industry jobs, and your login/corp-connect tokens - and
          signs you out. eve-build immediately loses the ability to act on your
          behalf. This doesn't revoke eve-build's access on EVE Online's side; do
          that from your EVE Online account's third-party application settings if
          you want that too. Corp-shared data (visible to other connected
          characters in your corp) isn't affected.
        </p>
        <div class="actions">
          <a class="btn btn-secondary" href="/settings/clear-data"
            onclick="return confirm(
              'Delete all eve-build data for this character and sign out? This cannot be undone.'
            )">
            Clear my data
          </a>
        </div>
      </div>
    """


@router.get("", response_class=HTMLResponse)
async def show_settings(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    account_section = _render_account_section(character)

    sources = await character_data.data_summary(db, character)
    data_section = _render_data_section(sources)

    corp_label = None
    status_rows = ""
    if character_data.corp_data_connected(character):
        corporation_id = cast(int, character.corporation_id)
        corp_access_token = cast(str, character.corp_access_token)
        corporation_name = await esi.get_corporation_name(settings, corporation_id)
        corp_label = escape(corporation_name or f"Corporation {corporation_id}")
        for label, fetch, required_role in _CORP_STATUS_SOURCES:
            result = await fetch(db, redis, settings, corp_access_token, corporation_id)
            if result is None:
                role_text = escape(required_role)
                status_html = (
                    f'<span class="status-missing">No permission &mdash; {role_text}</span>'
                )
            else:
                status_html = (
                    f'<span class="status-ok">Connected &middot; {len(result)} found</span>'
                )
            status_rows += f"<li><span>{escape(label)}</span>{status_html}</li>"
    corp_section = _render_corp_section(corp_label, status_rows)

    body = f"""<div class="page">
      <h1>Settings</h1>
      {account_section}
      {data_section}
      {corp_section}
      {_render_danger_section()}
    </div>"""
    safe_character = character.model_copy(
        update={
            "character_name": escape(character.character_name),
            "scopes": [escape(scope) for scope in character.scopes],
        }
    )
    return HTMLResponse(render_page("Settings", body, _STYLE, character=safe_character))


@router.get("/refresh")
async def refresh_data(
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
) -> RedirectResponse:
    await character_data.refresh_character_data(db, redis, character)
    return RedirectResponse("/settings")


@router.get("/clear-data")
async def clear_data(
    request: Request,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
) -> RedirectResponse:
    await character_data.clear_character_data(db, redis, character)
    request.session.clear()
    return RedirectResponse("/")
