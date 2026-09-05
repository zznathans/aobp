import pytest
from fastapi import FastAPI

import app.main as main_module
from app.core.config import get_settings


class _FakeMongoClient:
    def __init__(self) -> None:
        self.closed = False

    def __getitem__(self, name: str) -> object:
        return object()

    def close(self) -> None:
        self.closed = True


async def test_lifespan_closes_already_opened_clients_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "true")
    monkeypatch.setenv("SYNC_INDEXES_ON_STARTUP", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("RABBITMQ_ENABLED", "false")
    get_settings.cache_clear()

    fake_client = _FakeMongoClient()
    monkeypatch.setattr(main_module, "create_mongo_client", lambda settings: fake_client)

    async def _boom(db: object, settings: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "run_migrations", _boom)

    app = FastAPI()
    with pytest.raises(RuntimeError, match="boom"):
        async with main_module.lifespan(app):
            pass

    assert fake_client.closed is True

    get_settings.cache_clear()
