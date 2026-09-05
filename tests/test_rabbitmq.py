from app.db import rabbitmq


def test_scrape_job_message_roundtrips_through_json() -> None:
    message = rabbitmq.ScrapeJobMessage(region_id=10000002, scrape_run_id="run-1")

    decoded = rabbitmq.decode_scrape_job(rabbitmq.encode_scrape_job(message))

    assert decoded == message


def test_orders_chunk_message_roundtrips_through_json() -> None:
    message = rabbitmq.OrdersChunkMessage(
        region_id=10000002,
        scrape_run_id="run-1",
        orders=[{"order_id": 1, "type_id": 34, "price": 5.5}],
    )

    decoded = rabbitmq.decode_orders_chunk(rabbitmq.encode_orders_chunk(message))

    assert decoded == message
