from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.db.mongo import create_mongo_client
from app.db.redis import create_redis_client
from app.migrations.runner import run_migrations
from app.routes import auth, blueprints, health, jobs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.mongo_client = create_mongo_client(settings)
    app.state.redis = create_redis_client(settings)
    if settings.run_migrations_on_startup:
        await run_migrations(app.state.mongo_client[settings.mongodb_database], settings)
    try:
        yield
    finally:
        app.state.mongo_client.close()
        if app.state.redis is not None:
            await app.state.redis.aclose()


app = FastAPI(title="aobp", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=_settings.session_secret_key,
    session_cookie=_settings.session_cookie_name,
    max_age=_settings.session_max_age_seconds,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(blueprints.router)
app.include_router(jobs.router)
