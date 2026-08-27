from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character_optional
from app.models.character import CharacterDocument
from app.services import character_data, esi, industry, locations, sde
from app.services.locations import LocationInfo
from app.web import (
    gauge_cell_html,
    humanize_relative_time,
    icon_url,
    location_label_html,
    render_page,
)

router = APIRouter()

_LOGIN_STYLE = """
  body { display: flex; flex-direction: column; min-height: 100vh; }
  .login-wrap {
    flex: 1; display: flex; align-items: center; justify-content: center; padding: 2rem 1.5rem;
  }
  .card {
    background: #1a1d24;
    border: 1px solid #2a2e37;
    border-radius: 12px;
    padding: 2rem 2.5rem;
    width: 26rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }
  h1 { font-size: 1.25rem; margin: 0 0 0.75rem; font-weight: 600; text-align: center; }
  .tagline { color: #9aa4b2; font-size: 0.9rem; line-height: 1.5; margin: 0 0 1.25rem; }
  .feature-list {
    color: #9aa4b2; font-size: 0.85rem; line-height: 1.6;
    margin: 0 0 1.5rem; padding-left: 1.1rem;
  }
  .feature-list li { margin-bottom: 0.35rem; }
  .card .btn { width: 100%; }
"""

_DASHBOARD_STYLE = """
  .page { max-width: 70rem; margin: 0 auto; padding: 2rem 1.5rem; }
  h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
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
  .stat-card .figure { font-size: 2rem; font-weight: 700; }
  .stat-card .label { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  .stat-card a { text-decoration: none; color: inherit; }
  h2 { font-size: 1.05rem; margin: 0 0 0.75rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; margin-bottom: 2rem; }
  th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #2a2e37; }
  th { color: #9aa4b2; font-weight: 600; font-size: 0.7rem; text-transform: uppercase; }
  .empty { color: #9aa4b2; }
  .job-bp {
    display: flex; align-items: center; gap: 0.5rem;
    text-decoration: none; color: inherit;
  }
  .job-bp:hover span { color: #4c8bf5; }
  .job-bp .icon { width: 24px; height: 24px; border-radius: 4px; flex-shrink: 0; }
  table tr:hover td { background: #1a1d24; }
"""


def _render_login() -> str:
    body = """
      <div class="login-wrap">
        <div class="card">
          <h1>eve-build</h1>
          <p class="tagline">
            Imports your EVE Online characters' blueprints, assets, and industry jobs, so you
            can see what's buildable, what it's worth, and what's in production.
          </p>
          <ul class="feature-list">
            <li>Blueprint material/time efficiency and buildable-run counts, on-site and
              across all assets</li>
            <li>Assets by category - minerals, ore, PI materials, datacores, decryptors -
              with volume and ISK value</li>
            <li>Live market pricing</li>
            <li>Industry job status and progress</li>
          </ul>
          <form method="get" action="/auth/login">
            <button class="btn btn-primary" type="submit">Log in with EVE Online</button>
          </form>
        </div>
      </div>
    """
    return render_page("eve-build", body, _LOGIN_STYLE)


def _render_dashboard(
    character: CharacterDocument,
    blueprint_count: int,
    asset_count: int,
    active_jobs: list[esi.IndustryJobEntry],
    blueprint_type_docs: dict[int, dict[str, object]],
    job_location_info: dict[int, LocationInfo],
) -> str:
    def _job_row(job: esi.IndustryJobEntry) -> str:
        blueprint_name = escape(
            str(
                blueprint_type_docs.get(job.blueprint_type_id, {}).get(
                    "name", f"Type {job.blueprint_type_id}"
                )
            )
        )
        location_label = location_label_html(
            job.facility_id, job_location_info.get(job.facility_id)
        )
        job_href = escape(f"/jobs/{job.job_id}")
        activity_name = escape(
            industry.ACTIVITY_NAMES.get(job.activity_id, f"Activity {job.activity_id}")
        )
        end_date = escape(job.end_date)
        job_icon_url = escape(icon_url(job.blueprint_type_id))
        return f"""
          <tr>
            <td>
              <a class="job-bp" href="{job_href}">
                <img class="icon" src="{job_icon_url}" alt="{blueprint_name}">
                <span>{blueprint_name}</span>
              </a>
            </td>
            <td>{activity_name}</td>
            <td>{location_label}</td>
            <td>{job.runs}</td>
            <td>{gauge_cell_html(industry.job_progress_percentage(job))}</td>
            <td title="{end_date}">
              {humanize_relative_time(datetime.fromisoformat(job.end_date))}
            </td>
          </tr>
        """

    job_rows = "".join(_job_row(job) for job in active_jobs) or (
        '<tr><td colspan="6" class="empty">No running industry jobs.</td></tr>'
    )

    body = f"""<div class="page">
      <h1>Dashboard</h1>
      <div class="stat-grid">
        <a class="stat-card" href="/blueprints">
          <div class="figure">{blueprint_count}</div>
          <div class="label">Blueprints</div>
        </a>
        <a class="stat-card" href="/assets">
          <div class="figure">{asset_count}</div>
          <div class="label">Assets</div>
        </a>
        <div class="stat-card">
          <div class="figure">{len(active_jobs)}</div>
          <div class="label">Running industry jobs</div>
        </div>
      </div>
      <h2>Industry jobs</h2>
      <table>
        <thead>
          <tr>
            <th>Blueprint</th><th>Activity</th><th>Location</th><th>Runs</th>
            <th>Progress</th><th>Ends</th>
          </tr>
        </thead>
        <tbody>{job_rows}</tbody>
      </table>
    </div>"""
    return render_page("eve-build", body, _DASHBOARD_STYLE, character=character)


@router.get("/", response_class=HTMLResponse)
async def read_root(
    character: CharacterDocument | None = Depends(get_current_character_optional),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    if character is None:
        return HTMLResponse(_render_login())

    blueprints = await character_data.get_character_blueprints(
        db, redis, settings, character.access_token, character.character_id
    )
    assets = await character_data.get_character_assets(
        db, redis, settings, character.access_token, character.character_id
    )
    jobs = await character_data.get_character_industry_jobs(
        db, redis, settings, character.access_token, character.character_id
    )
    active_jobs = [job for job in jobs if job.status == "active"]
    blueprint_type_docs = await sde.type_docs(
        db, redis, settings, {job.blueprint_type_id for job in active_jobs}
    )
    job_location_info = await locations.resolve_location_info(
        db, redis, settings, character.access_token, {job.facility_id for job in active_jobs}
    )

    return HTMLResponse(
        _render_dashboard(
            character,
            len(blueprints),
            len(assets),
            active_jobs,
            blueprint_type_docs,
            job_location_info,
        )
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
