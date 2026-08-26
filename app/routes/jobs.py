from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import esi, industry, locations, sde
from app.web import gauge_cell_html, icon_url, render_page

router = APIRouter(prefix="/jobs", tags=["jobs"])

_DETAIL_STYLE = """
  .page { max-width: 36rem; margin: 0 auto; padding: 2rem 1.5rem; }
  .header { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
  .header .icon { width: 64px; height: 64px; border-radius: 8px; }
  .header .name { font-size: 1.3rem; font-weight: 600; }
  .header .meta { color: #9aa4b2; font-size: 0.85rem; margin-top: 0.25rem; }
  .facts { background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 1rem; }
  .facts dl { margin: 0; display: grid; grid-template-columns: 10rem 1fr; row-gap: 0.75rem; }
  .facts dt { color: #9aa4b2; font-size: 0.8rem; }
  .facts dd { margin: 0; }
  .back { display: inline-block; margin-top: 1.5rem; }
"""


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_detail(
    job_id: int,
    character: CharacterDocument = Depends(get_current_character),
    db: AsyncIOMotorDatabase = Depends(get_database),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    jobs = await esi.get_character_industry_jobs(
        settings, character.access_token, character.character_id
    )
    job = next((j for j in jobs if j.job_id == job_id), None)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    type_ids = {job.blueprint_type_id}
    if job.product_type_id is not None:
        type_ids.add(job.product_type_id)
    type_docs = await sde.type_docs(db, redis, settings, type_ids)
    location_names = await locations.resolve_location_names(
        db, redis, settings, character.access_token, {job.facility_id}
    )

    blueprint_name = escape(
        str(type_docs.get(job.blueprint_type_id, {}).get("name", f"Type {job.blueprint_type_id}"))
    )
    location_label = escape(location_names.get(job.facility_id) or f"Location {job.facility_id}")
    activity_name = escape(
        industry.ACTIVITY_NAMES.get(job.activity_id, f"Activity {job.activity_id}")
    )
    status_label = escape(job.status.capitalize())
    start_date = escape(job.start_date)
    end_date = escape(job.end_date)

    product_row = ""
    if job.product_type_id is not None:
        product_name = escape(
            str(type_docs.get(job.product_type_id, {}).get("name", f"Type {job.product_type_id}"))
        )
        product_row = f"<dt>Product</dt><dd>{product_name}</dd>"

    header = f"""
      <div class="header">
        <img class="icon" src="{escape(icon_url(job.blueprint_type_id))}" alt="{blueprint_name}">
        <div>
          <div class="name">{blueprint_name}</div>
          <div class="meta">{activity_name} &middot; {status_label}</div>
        </div>
      </div>
    """

    body = f"""<div class="page">{header}
      <div class="facts">
        <dl>
          <dt>Location</dt><dd>{location_label}</dd>
          <dt>Runs</dt><dd>{job.runs}</dd>
          <dt>Progress</dt><dd>{gauge_cell_html(industry.job_progress_percentage(job))}</dd>
          <dt>Started</dt><dd>{start_date}</dd>
          <dt>Ends</dt><dd>{end_date}</dd>
          {product_row}
        </dl>
      </div>
      <a class="btn btn-secondary back" href="/">Back to dashboard</a>
    </div>"""
    return HTMLResponse(
        render_page(f"{blueprint_name} - eve-build", body, _DETAIL_STYLE, character=character)
    )
