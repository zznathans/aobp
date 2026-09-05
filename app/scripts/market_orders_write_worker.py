"""Long-running worker: consumes market-order result chunks and dumps them wholesale into the
`market_orders` collection - one row per order per scrape run, deduped on redelivery. Old rows
are expected to be expired by a TTL index rather than swept here.

Usage:
    python -m app.scripts.market_orders_write_worker
"""

import asyncio
import logging

from app.core.config import get_settings
from app.db.mongo import create_mongo_client
from app.db.rabbitmq import (
    create_rabbitmq_connection,
    declare_market_order_queues,
    decode_orders_chunk,
)
from app.services.market_orders import apply_orders_chunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eve-build.market_orders.write_worker")


async def main() -> None:
    settings = get_settings()
    connection = await create_rabbitmq_connection(settings)
    if connection is None:
        raise RuntimeError("RabbitMQ is disabled (RABBITMQ_ENABLED=false) - can't run this worker")

    mongo_client = create_mongo_client(settings)
    try:
        db = mongo_client[settings.mongodb_database]

        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=settings.market_orders_write_prefetch)
            _, results_queue = await declare_market_order_queues(channel)

            async with results_queue.iterator() as messages:
                async for message in messages:
                    result = decode_orders_chunk(message.body)
                    count = await apply_orders_chunk(db, result)
                    logger.info("Inserted %s orders for region %s", count, result.region_id)
                    await message.ack()
    finally:
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
