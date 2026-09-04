import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings
from app.db import rabbitmq
from app.services import esi

# Queue name + message payload, so a caller doesn't need aio_pika in scope to publish -
# tests pass a fake that just appends to a list, matching how respx fakes ESI elsewhere.
Publish = Callable[[str, bytes], Awaitable[None]]


async def dispatch_scrape(settings: Settings, publish: Publish) -> str:
    """Enqueues one scrape job per public region under a fresh scrape_run_id. Returns the
    scrape_run_id so callers (e.g. the CLI entrypoint) can log it."""
    scrape_run_id = str(uuid.uuid4())
    region_ids = await esi.get_region_ids(settings)

    for region_id in region_ids:
        message = rabbitmq.ScrapeJobMessage(region_id=region_id, scrape_run_id=scrape_run_id)
        await publish(rabbitmq.MARKET_ORDERS_SCRAPE_JOBS_QUEUE, rabbitmq.encode_scrape_job(message))

    return scrape_run_id


async def run_fetch_job(
    settings: Settings, job: rabbitmq.ScrapeJobMessage, publish: Publish
) -> None:
    """Fetches every page of a region's market orders, publishes them to the results queue in
    chunks, then a RegionCompleteMessage so the write worker knows when it's safe to sweep stale
    orders for that region+run. Regions with no market (404) yield zero orders/pages."""
    orders: list[esi.MarketOrderEntry] = []

    first_page, total_pages = await esi.get_market_orders_page(settings, job.region_id, 1)
    orders.extend(first_page)

    for page in range(2, total_pages + 1):
        page_orders, _ = await esi.get_market_orders_page(settings, job.region_id, page)
        orders.extend(page_orders)

    for start in range(0, len(orders), settings.market_orders_chunk_size):
        chunk = orders[start : start + settings.market_orders_chunk_size]
        chunk_message = rabbitmq.OrdersChunkMessage(
            region_id=job.region_id,
            scrape_run_id=job.scrape_run_id,
            orders=[asdict(entry) for entry in chunk],
        )
        await publish(
            rabbitmq.MARKET_ORDERS_RESULTS_QUEUE, rabbitmq.encode_result_message(chunk_message)
        )

    complete_message = rabbitmq.RegionCompleteMessage(
        region_id=job.region_id, scrape_run_id=job.scrape_run_id, order_count=len(orders)
    )
    await publish(
        rabbitmq.MARKET_ORDERS_RESULTS_QUEUE, rabbitmq.encode_result_message(complete_message)
    )


async def _upsert_order(
    db: AsyncIOMotorDatabase,
    order: dict[str, Any],
    region_id: int,
    scrape_run_id: str,
    now: datetime,
) -> None:
    fields = {key: value for key, value in order.items() if key != "order_id"}
    await db.market_orders.update_one(
        {"_id": order["order_id"]},
        {
            "$set": {
                **fields,
                "region_id": region_id,
                "scrape_run_id": scrape_run_id,
                "scraped_at": now,
            }
        },
        upsert=True,
    )


async def apply_orders_chunk(db: AsyncIOMotorDatabase, message: rabbitmq.OrdersChunkMessage) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)

    await asyncio.gather(
        *(
            _upsert_order(db, order, message.region_id, message.scrape_run_id, now)
            for order in message.orders
        )
    )

    history_docs = [
        {
            **order,
            "region_id": message.region_id,
            "scrape_run_id": message.scrape_run_id,
            "scraped_at": now,
        }
        for order in message.orders
    ]
    if history_docs:
        try:
            await db.market_order_history.insert_many(history_docs, ordered=False)
        except pymongo.errors.BulkWriteError as exc:
            write_errors = exc.details.get("writeErrors", []) if exc.details else []
            if any(error.get("code") != 11000 for error in write_errors):
                raise

    return len(message.orders)


async def apply_region_complete(
    db: AsyncIOMotorDatabase, message: rabbitmq.RegionCompleteMessage
) -> int:
    """Sweeps market_orders docs for this region that weren't refreshed by this scrape run -
    i.e. orders that filled, were canceled, or expired since the last scrape."""
    result = await db.market_orders.delete_many(
        {"region_id": message.region_id, "scrape_run_id": {"$ne": message.scrape_run_id}}
    )
    return int(result.deleted_count)
