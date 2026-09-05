import json
from dataclasses import asdict, dataclass
from typing import Any

import aio_pika
from fastapi import Request

from app.core.config import Settings

MARKET_ORDERS_SCRAPE_JOBS_QUEUE = "market_orders.scrape_jobs"
MARKET_ORDERS_RESULTS_QUEUE = "market_orders.results"


async def create_rabbitmq_connection(
    settings: Settings,
) -> aio_pika.abc.AbstractRobustConnection | None:
    if not settings.rabbitmq_enabled:
        return None
    return await aio_pika.connect_robust(settings.rabbitmq_url)


def get_rabbitmq(request: Request) -> aio_pika.abc.AbstractRobustConnection | None:
    return request.app.state.rabbitmq


async def declare_market_order_queues(
    channel: aio_pika.abc.AbstractChannel,
) -> tuple[aio_pika.abc.AbstractQueue, aio_pika.abc.AbstractQueue]:
    scrape_jobs_queue = await channel.declare_queue(MARKET_ORDERS_SCRAPE_JOBS_QUEUE, durable=True)
    results_queue = await channel.declare_queue(MARKET_ORDERS_RESULTS_QUEUE, durable=True)
    return scrape_jobs_queue, results_queue


@dataclass(frozen=True)
class ScrapeJobMessage:
    region_id: int
    scrape_run_id: str


@dataclass(frozen=True)
class OrdersChunkMessage:
    region_id: int
    scrape_run_id: str
    orders: list[dict[str, Any]]


def encode_scrape_job(message: ScrapeJobMessage) -> bytes:
    return json.dumps(asdict(message)).encode("utf-8")


def decode_scrape_job(payload: bytes) -> ScrapeJobMessage:
    return ScrapeJobMessage(**json.loads(payload))


def encode_orders_chunk(message: OrdersChunkMessage) -> bytes:
    return json.dumps(asdict(message)).encode("utf-8")


def decode_orders_chunk(payload: bytes) -> OrdersChunkMessage:
    return OrdersChunkMessage(**json.loads(payload))
