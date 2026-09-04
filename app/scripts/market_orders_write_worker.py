"""Long-running worker: consumes market-order results (order chunks + region-complete markers)
and persists them to MongoDB - upserting the live `market_orders` snapshot, appending to
`market_order_history`, and sweeping stale snapshot docs once a region's scrape run is complete.

Usage:
    python -m app.scripts.market_orders_write_worker
"""

import asyncio
import logging

from app.core.config import get_settings
from app.db.mongo import create_mongo_client
from app.db.rabbitmq import (
    OrdersChunkMessage,
    create_rabbitmq_connection,
    declare_market_order_queues,
    decode_result_message,
)
from app.services.market_orders import apply_orders_chunk, apply_region_complete

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("eve-build.market_orders.write_worker")


async def main() -> None:
    settings = get_settings()
    connection = await create_rabbitmq_connection(settings)
    if connection is None:
        raise RuntimeError("RabbitMQ is disabled (RABBITMQ_ENABLED=false) - can't run this worker")

    mongo_client = create_mongo_client(settings)
    db = mongo_client[settings.mongodb_database]

    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.market_orders_write_prefetch)
        _, results_queue = await declare_market_order_queues(channel)

        async with results_queue.iterator() as messages:
            async for message in messages:
                result = decode_result_message(message.body)
                if isinstance(result, OrdersChunkMessage):
                    count = await apply_orders_chunk(db, result)
                    logger.info("Upserted %s orders for region %s", count, result.region_id)
                else:
                    deleted = await apply_region_complete(db, result)
                    logger.info(
                        "Region %s scrape complete (%s orders), swept %s stale orders",
                        result.region_id,
                        result.order_count,
                        deleted,
                    )
                await message.ack()

    mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
