import aio_pika
from fastapi import Request

from app.core.config import Settings


async def create_rabbitmq_connection(
    settings: Settings,
) -> aio_pika.abc.AbstractRobustConnection | None:
    if not settings.rabbitmq_enabled:
        return None
    return await aio_pika.connect_robust(settings.rabbitmq_url)


def get_rabbitmq(request: Request) -> aio_pika.abc.AbstractRobustConnection | None:
    return request.app.state.rabbitmq
