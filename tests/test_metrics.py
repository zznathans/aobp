import importlib

import pytest
from fastapi.testclient import TestClient

import app.main
from app.core.config import get_settings


def test_metrics_disabled_by_default(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 404


def test_metrics_endpoint_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("SYNC_INDEXES_ON_STARTUP", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("METRICS_DB_GAUGES_ENABLED", "false")
    get_settings.cache_clear()
    importlib.reload(app.main)
    try:
        with TestClient(app.main.app) as test_client:
            response = test_client.get("/metrics")
        assert response.status_code == 200
        assert b"# HELP" in response.content
        assert b"eve_build_cache_hits_total" in response.content
    finally:
        monkeypatch.setenv("METRICS_ENABLED", "false")
        get_settings.cache_clear()
        importlib.reload(app.main)


def test_health_still_works_when_metrics_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("SYNC_INDEXES_ON_STARTUP", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("METRICS_DB_GAUGES_ENABLED", "false")
    get_settings.cache_clear()
    importlib.reload(app.main)
    try:
        with TestClient(app.main.app) as test_client:
            response = test_client.get("/health")
        assert response.status_code == 200
    finally:
        monkeypatch.setenv("METRICS_ENABLED", "false")
        get_settings.cache_clear()
        importlib.reload(app.main)
