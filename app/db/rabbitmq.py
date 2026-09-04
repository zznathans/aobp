import json
from dataclasses import asdict, dataclass
from typing import Any

import aio_pika
from fastapi import Request

from app.core.config import Settings

MARKET_ORDERS_SCRAPE_JOBS_QUEUE = "market_orders.scrape_jobs"
MARKET_ORDERS_RESULTS_QUEUE = "market_orders.results"

_ORDERS_CHUNK_TYPE = "orders_chunk"
_REGION_COMPLETE_TYPE = "region_complete"


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


@dataclass(frozen=True)
class RegionCompleteMessage:
    region_id: int
    scrape_run_id: str
    order_count: int


ResultMessage = OrdersChunkMessage | RegionCompleteMessage


def encode_scrape_job(message: ScrapeJobMessage) -> bytes:
    return json.dumps(asdict(message)).encode("utf-8")


def decode_scrape_job(payload: bytes) -> ScrapeJobMessage:
    return ScrapeJobMessage(**json.loads(payload))


def encode_result_message(message: ResultMessage) -> bytes:
    if isinstance(message, OrdersChunkMessage):
        body: dict[str, Any] = {"type": _ORDERS_CHUNK_TYPE, **asdict(message)}
    else:
        body = {"type": _REGION_COMPLETE_TYPE, **asdict(message)}
    return json.dumps(body).encode("utf-8")


def decode_result_message(payload: bytes) -> ResultMessage:
    body = json.loads(payload)
    message_type = body.pop("type")
    if message_type == _ORDERS_CHUNK_TYPE:
        return OrdersChunkMessage(**body)
    if message_type == _REGION_COMPLETE_TYPE:
        return RegionCompleteMessage(**body)
    raise ValueError(f"Unknown market order result message type: {message_type!r}")
