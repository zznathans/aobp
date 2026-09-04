"""Long-running worker: consumes market-order scrape jobs, fetches every page of that region's
orders from ESI (retrying transient errors and backing off on ESI's error-rate limit), and
publishes them - chunked, plus a final region-complete marker - to the results queue for a write
worker to persist. Run as a Deployment; scale replicas to parallelize across regions.

Usage:
    python -m app.scripts.market_orders_fetch_worker
"""

import asyncio
import logging

import aio_pika

from app.core.config import get_settings
from app.db.rabbitmq import (
    create_rabbitmq_connection,
    declare_market_order_queues,
    decode_scrape_job,
)
from app.services.market_orders import run_fetch_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eve-build.market_orders.fetch_worker")


async def main() -> None:
    settings = get_settings()
    connection = await create_rabbitmq_connection(settings)
    if connection is None:
        raise RuntimeError("RabbitMQ is disabled (RABBITMQ_ENABLED=false) - can't run this worker")

    async with connection:
        channel = await connection.channel()
        scrape_jobs_queue, _ = await declare_market_order_queues(channel)

        async def publish(queue_name: str, body: bytes) -> None:
            await channel.default_exchange.publish(
                aio_pika.Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=queue_name,
            )

        async with scrape_jobs_queue.iterator() as messages:
            async for message in messages:
                job = decode_scrape_job(message.body)
                logger.info("Fetching market orders for region %s", job.region_id)
                # Ack only after every chunk + the region-complete marker publish succeeds - a
                # crash mid-fetch leaves the job unacked, so RabbitMQ redelivers it and another
                # worker retries the whole region. Safe: writes downstream are idempotent.
                await run_fetch_job(settings, job, publish)
                await message.ack()
                logger.info("Finished region %s", job.region_id)


if __name__ == "__main__":
    asyncio.run(main())
