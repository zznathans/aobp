import respx
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.db import rabbitmq
from app.services import market_orders

_SAMPLE_ORDER = {
    "order_id": 1,
    "type_id": 34,
    "location_id": 60003760,
    "is_buy_order": False,
    "price": 5.5,
    "volume_remain": 100,
    "volume_total": 200,
    "min_volume": 1,
    "duration": 90,
    "issued": "2026-01-01T00:00:00Z",
    "range": "region",
}


class _RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []

    async def __call__(self, queue_name: str, body: bytes) -> None:
        self.messages.append((queue_name, body))


@respx.mock
async def test_dispatch_scrape_enqueues_one_job_per_region() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/universe/regions/").mock(
        return_value=Response(200, json=[10000002, 10000043])
    )
    publisher = _RecordingPublisher()

    scrape_run_id = await market_orders.dispatch_scrape(settings, publisher)

    assert len(publisher.messages) == 2
    jobs = [
        rabbitmq.decode_scrape_job(body)
        for queue_name, body in publisher.messages
        if queue_name == rabbitmq.MARKET_ORDERS_SCRAPE_JOBS_QUEUE
    ]
    assert {job.region_id for job in jobs} == {10000002, 10000043}
    assert all(job.scrape_run_id == scrape_run_id for job in jobs)


@respx.mock
async def test_run_fetch_job_chunks_orders_and_publishes_region_complete() -> None:
    settings = Settings(market_orders_chunk_size=1)
    respx.get(f"{settings.esi_base_url}/markets/10000002/orders/", params={"page": 1}).mock(
        return_value=Response(200, headers={"X-Pages": "2"}, json=[_SAMPLE_ORDER])
    )
    respx.get(f"{settings.esi_base_url}/markets/10000002/orders/", params={"page": 2}).mock(
        return_value=Response(
            200, headers={"X-Pages": "2"}, json=[{**_SAMPLE_ORDER, "order_id": 2}]
        )
    )
    publisher = _RecordingPublisher()
    job = rabbitmq.ScrapeJobMessage(region_id=10000002, scrape_run_id="run-1")

    await market_orders.run_fetch_job(settings, job, publisher)

    chunk_messages = []
    complete_messages = []
    for queue_name, body in publisher.messages:
        assert queue_name == rabbitmq.MARKET_ORDERS_RESULTS_QUEUE
        decoded = rabbitmq.decode_result_message(body)
        if isinstance(decoded, rabbitmq.OrdersChunkMessage):
            chunk_messages.append(decoded)
        else:
            complete_messages.append(decoded)

    assert len(chunk_messages) == 2  # chunk_size=1, two orders fetched
    assert {chunk.orders[0]["order_id"] for chunk in chunk_messages} == {1, 2}
    assert complete_messages == [
        rabbitmq.RegionCompleteMessage(region_id=10000002, scrape_run_id="run-1", order_count=2)
    ]


@respx.mock
async def test_run_fetch_job_handles_region_with_no_market() -> None:
    settings = Settings()
    respx.get(f"{settings.esi_base_url}/markets/10000004/orders/", params={"page": 1}).mock(
        return_value=Response(404, json={"error": "Region not found"})
    )
    publisher = _RecordingPublisher()
    job = rabbitmq.ScrapeJobMessage(region_id=10000004, scrape_run_id="run-1")

    await market_orders.run_fetch_job(settings, job, publisher)

    assert len(publisher.messages) == 1
    decoded = rabbitmq.decode_result_message(publisher.messages[0][1])
    assert decoded == rabbitmq.RegionCompleteMessage(
        region_id=10000004, scrape_run_id="run-1", order_count=0
    )


async def test_apply_orders_chunk_upserts_snapshot_and_appends_history(
    mongo_db: AsyncMongoMockClient,
) -> None:
    message = rabbitmq.OrdersChunkMessage(
        region_id=10000002, scrape_run_id="run-1", orders=[_SAMPLE_ORDER]
    )

    count = await market_orders.apply_orders_chunk(mongo_db, message)

    assert count == 1
    snapshot = await mongo_db.market_orders.find_one({"_id": 1})
    assert snapshot is not None
    assert snapshot["region_id"] == 10000002
    assert snapshot["scrape_run_id"] == "run-1"
    assert snapshot["price"] == 5.5

    history = await mongo_db.market_order_history.find_one(
        {"order_id": 1, "scrape_run_id": "run-1"}
    )
    assert history is not None
    assert history["region_id"] == 10000002


async def test_apply_orders_chunk_ignores_duplicate_history_on_redelivery(
    mongo_db: AsyncMongoMockClient,
) -> None:
    await mongo_db.market_order_history.create_index(
        [("order_id", 1), ("scrape_run_id", 1)], unique=True
    )
    message = rabbitmq.OrdersChunkMessage(
        region_id=10000002, scrape_run_id="run-1", orders=[_SAMPLE_ORDER]
    )

    await market_orders.apply_orders_chunk(mongo_db, message)
    await market_orders.apply_orders_chunk(mongo_db, message)  # redelivered chunk

    history_count = await mongo_db.market_order_history.count_documents(
        {"order_id": 1, "scrape_run_id": "run-1"}
    )
    assert history_count == 1


async def test_apply_region_complete_sweeps_only_stale_orders_for_that_region(
    mongo_db: AsyncMongoMockClient,
) -> None:
    await mongo_db.market_orders.insert_many(
        [
            {"_id": 1, "region_id": 10000002, "scrape_run_id": "run-0"},  # stale, same region
            {"_id": 2, "region_id": 10000002, "scrape_run_id": "run-1"},  # fresh, same region
            {"_id": 3, "region_id": 10000043, "scrape_run_id": "run-0"},  # different region
        ]
    )
    message = rabbitmq.RegionCompleteMessage(
        region_id=10000002, scrape_run_id="run-1", order_count=1
    )

    deleted = await market_orders.apply_region_complete(mongo_db, message)

    assert deleted == 1
    remaining_ids = {doc["_id"] async for doc in mongo_db.market_orders.find({}, {"_id": 1})}
    assert remaining_ids == {2, 3}
