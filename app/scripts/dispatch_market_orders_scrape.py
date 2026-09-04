"""One-shot dispatcher: enqueues a market-order scrape job for every public region. Run
periodically by the market-orders-dispatch CronJob; the actual fetching happens in
market_orders_fetch_worker.py, consuming the queue this publishes to.

Usage:
    python -m app.scripts.dispatch_market_orders_scrape
"""

import asyncio
import logging

import aio_pika

from app.core.config import get_settings
from app.db.rabbitmq import create_rabbitmq_connection, declare_market_order_queues
from app.services.market_orders import dispatch_scrape

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eve-build.market_orders.dispatch")


async def main() -> None:
    settings = get_settings()
    connection = await create_rabbitmq_connection(settings)
    if connection is None:
        raise RuntimeError(
            "RabbitMQ is disabled (RABBITMQ_ENABLED=false) - can't dispatch a scrape"
        )

    async with connection:
        channel = await connection.channel()
        await declare_market_order_queues(channel)

        async def publish(queue_name: str, body: bytes) -> None:
            await channel.default_exchange.publish(
                aio_pika.Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
                routing_key=queue_name,
            )

        scrape_run_id = await dispatch_scrape(settings, publish)
        logger.info("Dispatched market order scrape run %s", scrape_run_id)


if __name__ == "__main__":
    asyncio.run(main())
