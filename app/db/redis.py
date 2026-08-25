from fastapi import Request
from redis.asyncio import Redis

from app.core.config import Settings


def create_redis_client(settings: Settings) -> Redis | None:
    if not settings.redis_enabled:
        return None
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis(request: Request) -> Redis | None:
    return request.app.state.redis
