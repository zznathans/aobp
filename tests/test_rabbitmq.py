import json

import pytest

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

    decoded = rabbitmq.decode_result_message(rabbitmq.encode_result_message(message))

    assert decoded == message


def test_region_complete_message_roundtrips_through_json() -> None:
    message = rabbitmq.RegionCompleteMessage(
        region_id=10000002, scrape_run_id="run-1", order_count=42
    )

    decoded = rabbitmq.decode_result_message(rabbitmq.encode_result_message(message))

    assert decoded == message


def test_decode_result_message_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="Unknown market order result message type"):
        rabbitmq.decode_result_message(json.dumps({"type": "bogus"}).encode("utf-8"))
