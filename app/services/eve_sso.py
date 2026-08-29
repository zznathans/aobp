import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWK

from app.core.config import Settings


@dataclass(frozen=True)
class PkcePair:
    code_verifier: str
    code_challenge: str


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True)
class CharacterClaims:
    character_id: int
    character_name: str
    owner_hash: str
    scopes: list[str]


def generate_pkce_pair() -> PkcePair:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkcePair(code_verifier=code_verifier, code_challenge=code_challenge)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(
    settings: Settings, *, code_challenge: str, state: str, scope: str | None = None
) -> str:
    params = {
        "response_type": "code",
        "redirect_uri": settings.eve_sso_callback_url,
        "client_id": settings.eve_sso_client_id,
        "scope": scope if scope is not None else settings.eve_sso_scopes,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{settings.eve_sso_authorize_url}?{urlencode(params)}"


async def exchange_code_for_token(
    settings: Settings, *, code: str, code_verifier: str
) -> TokenResponse:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.eve_sso_client_id,
        "code_verifier": code_verifier,
    }
    return await _request_token(settings, data)


async def refresh_access_token(settings: Settings, *, refresh_token: str) -> TokenResponse:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.eve_sso_client_id,
    }
    return await _request_token(settings, data)


async def _request_token(settings: Settings, data: dict[str, str]) -> TokenResponse:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "login.eveonline.com",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(settings.eve_sso_token_url, data=data, headers=headers)
    response.raise_for_status()
    payload = response.json()
    return TokenResponse(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_in=payload["expires_in"],
    )


async def validate_access_token(settings: Settings, access_token: str) -> CharacterClaims:
    async with httpx.AsyncClient() as client:
        jwks_response = await client.get(settings.eve_sso_jwks_url)
    jwks_response.raise_for_status()
    jwk_set = jwks_response.json()

    unverified_header = jwt.get_unverified_header(access_token)
    key_id = unverified_header.get("kid")
    matching_jwk = next((key for key in jwk_set["keys"] if key.get("kid") == key_id), None)
    if matching_jwk is None:
        raise jwt.InvalidTokenError(f"No matching JWK found for kid={key_id!r}")
    signing_key = PyJWK.from_dict(matching_jwk)

    claims = jwt.decode(
        access_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        issuer=settings.eve_sso_issuer,
        audience=settings.eve_sso_audience,
    )

    subject: str = claims["sub"]
    character_id = int(subject.removeprefix("CHARACTER:EVE:"))
    scopes_claim = claims.get("scp", [])
    scopes = scopes_claim if isinstance(scopes_claim, list) else [scopes_claim]

    return CharacterClaims(
        character_id=character_id,
        character_name=claims["name"],
        owner_hash=claims["owner"],
        scopes=scopes,
    )
