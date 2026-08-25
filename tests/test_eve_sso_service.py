import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response

from app.core.config import Settings
from app.services import eve_sso
from tests.conftest import make_access_token


def test_generate_pkce_pair_challenge_matches_verifier() -> None:
    pair = eve_sso.generate_pkce_pair()
    expected_digest = hashlib.sha256(pair.code_verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(expected_digest).decode("ascii").rstrip("=")
    assert pair.code_challenge == expected_challenge
    assert "=" not in pair.code_challenge


def test_build_authorize_url_contains_expected_params() -> None:
    settings = Settings(
        eve_sso_client_id="my-client-id",
        eve_sso_callback_url="http://testserver/auth/callback",
        eve_sso_scopes="publicData",
    )
    url = eve_sso.build_authorize_url(settings, code_challenge="abc123", state="xyz789")

    parsed = urlparse(url)
    assert parsed.netloc == "login.eveonline.com"
    query = parse_qs(parsed.query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["my-client-id"]
    assert query["redirect_uri"] == ["http://testserver/auth/callback"]
    assert query["scope"] == ["publicData"]
    assert query["code_challenge"] == ["abc123"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["xyz789"]


@pytest.mark.asyncio
@respx.mock
async def test_validate_access_token_valid(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, jwk = rsa_key_pair
    settings = Settings(eve_sso_issuer="https://login.eveonline.com", eve_sso_audience="EVE Online")
    respx.get(settings.eve_sso_jwks_url).mock(return_value=Response(200, json={"keys": [jwk]}))
    token = make_access_token(
        private_key,
        character_id=98765,
        character_name="Some Pilot",
        owner_hash="owner-hash-1",
        scopes=["publicData"],
    )

    claims = await eve_sso.validate_access_token(settings, token)

    assert claims.character_id == 98765
    assert claims.character_name == "Some Pilot"
    assert claims.owner_hash == "owner-hash-1"
    assert claims.scopes == ["publicData"]


@pytest.mark.asyncio
@respx.mock
async def test_validate_access_token_wrong_issuer_rejected(
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, jwk = rsa_key_pair
    settings = Settings(eve_sso_issuer="https://login.eveonline.com", eve_sso_audience="EVE Online")
    respx.get(settings.eve_sso_jwks_url).mock(return_value=Response(200, json={"keys": [jwk]}))
    token = make_access_token(private_key, issuer="not-eve-online")

    with pytest.raises(jwt.InvalidIssuerError):
        await eve_sso.validate_access_token(settings, token)
