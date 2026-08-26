import base64
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.db.redis import get_redis
from app.main import app

TEST_KEY_ID = "test-key-1"


@pytest.fixture
def rsa_key_pair() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _int_to_b64url(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).decode("ascii").rstrip("=")

    jwk = {
        "kty": "RSA",
        "kid": TEST_KEY_ID,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_b64url(public_numbers.n),
        "e": _int_to_b64url(public_numbers.e),
    }
    return private_key, jwk


@pytest.fixture
def mongo_db() -> object:
    client = AsyncMongoMockClient()
    return client["eve-build"]


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        eve_sso_client_id="test-client-id",
        eve_sso_callback_url="http://testserver/auth/callback",
        eve_sso_scopes="",
        session_secret_key="test-secret",
        mongodb_uri="mongodb://localhost:27017",
        mongodb_database="eve-build",
    )


@pytest.fixture
def client(
    mongo_db: object, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    # `lifespan` calls get_settings() directly (not via Depends), so dependency_overrides
    # can't reach it — disable the startup migration and Redis via env vars instead, since
    # they'd otherwise hit the real local MongoDB/Redis (e.g. if REDIS_ENABLED=true in a
    # developer's .env, every test would silently read/write the real Redis instance).
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    get_settings.cache_clear()
    app.dependency_overrides[get_database] = lambda: mongo_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client_with_redis(client: TestClient, fake_redis: FakeRedis) -> TestClient:
    app.dependency_overrides[get_redis] = lambda: fake_redis
    return client


def make_access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    character_id: int = 12345,
    character_name: str = "Test Character",
    owner_hash: str = "test-owner-hash",
    scopes: list[str] | None = None,
    issuer: str = "https://login.eveonline.com",
    audience: str = "EVE Online",
) -> str:
    claims = {
        "sub": f"CHARACTER:EVE:{character_id}",
        "name": character_name,
        "owner": owner_hash,
        "scp": scopes or [],
        "iss": issuer,
        "aud": audience,
    }
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": TEST_KEY_ID})
