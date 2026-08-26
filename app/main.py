import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.db.mongo import create_mongo_client
from app.db.redis import create_redis_client
from app.migrations.runner import run_migrations
from app.routes import auth, blueprints, health, jobs, market_prices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eve-build")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting up")

    settings = get_settings()
    app.state.settings = settings
    logger.info("Loaded settings (mongodb_database=%s)", settings.mongodb_database)

    app.state.mongo_client = create_mongo_client(settings)
    logger.info("MongoDB client created for database %r", settings.mongodb_database)

    app.state.redis = create_redis_client(settings)
    if app.state.redis is not None:
        logger.info("Redis client created (redis_url=%s)", settings.redis_url)
    else:
        logger.info("Redis disabled, skipping cache client")

    if settings.run_migrations_on_startup:
        logger.info("Running database migrations")
        await run_migrations(app.state.mongo_client[settings.mongodb_database], settings)
        logger.info("Database migrations complete")
    else:
        logger.info("Skipping database migrations (run_migrations_on_startup=False)")

    logger.info("Startup complete")
    try:
        yield
    finally:
        logger.info("Shutting down")
        app.state.mongo_client.close()
        if app.state.redis is not None:
            await app.state.redis.aclose()
        logger.info("Shutdown complete")


app = FastAPI(title="eve-build", lifespan=lifespan)

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
app.include_router(market_prices.router)
