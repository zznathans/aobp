from urllib.parse import parse_qs, urlparse

import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from tests.conftest import make_access_token

CHARACTER_ID = 555
CORPORATION_ID = 98000001
TRITANIUM_TYPE_ID = 34


def _log_in(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    private_key, jwk = rsa_key_pair
    login_response = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]

    access_token = make_access_token(
        private_key, character_id=CHARACTER_ID, character_name="Alt Pilot"
    )
    respx.post(test_settings.eve_sso_token_url).mock(
        return_value=Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "refresh-token-value",
                "expires_in": 1200,
            },
        )
    )
    respx.get(test_settings.eve_sso_jwks_url).mock(return_value=Response(200, json={"keys": [jwk]}))

    client.get(
        "/auth/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )


def _connect_corp(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
    *,
    character_id: int = CHARACTER_ID,
    character_name: str = "Alt Pilot",
) -> Response:
    private_key, jwk = rsa_key_pair
    connect_response = client.get("/auth/connect-corp", follow_redirects=False)
    state = parse_qs(urlparse(connect_response.headers["location"]).query)["state"][0]

    access_token = make_access_token(
        private_key, character_id=character_id, character_name=character_name
    )
    respx.post(test_settings.eve_sso_token_url).mock(
        return_value=Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "corp-refresh-token-value",
                "expires_in": 1200,
            },
        )
    )
    respx.get(test_settings.eve_sso_jwks_url).mock(return_value=Response(200, json={"keys": [jwk]}))
    respx.get(f"{test_settings.esi_base_url}/characters/{character_id}/").mock(
        return_value=Response(200, json={"corporation_id": CORPORATION_ID})
    )

    return client.get(
        "/auth/connect-corp/callback",
        params={"code": "corp-auth-code", "state": state},
        follow_redirects=False,
    )


@respx.mock
def test_connect_corp_redirects_with_corp_scope(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    test_settings.eve_sso_corp_scopes = "esi-assets.read_corporation_assets.v1"
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/auth/connect-corp", follow_redirects=False)

    assert response.status_code in (302, 307)
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["esi-assets.read_corporation_assets.v1"]


@respx.mock
def test_connect_corp_callback_happy_path(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = _connect_corp(client, test_settings, rsa_key_pair)

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/settings"

    respx.get(f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/").mock(
        return_value=Response(200, json={"name": "Test Corp"})
    )
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/assets", params={"page": 1}
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/blueprints",
        params={"page": 1},
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/industry/jobs",
        params={"page": 1},
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))

    settings_response = client.get("/settings")
    assert settings_response.status_code == 200
    assert "Test Corp" in settings_response.text
    assert "Disconnect" in settings_response.text


@respx.mock
def test_connect_corp_callback_rejects_mismatched_character(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = _connect_corp(
        client, test_settings, rsa_key_pair, character_id=999, character_name="Some Other Alt"
    )

    assert response.status_code == 400


@respx.mock
def test_disconnect_corp_clears_connection(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    _connect_corp(client, test_settings, rsa_key_pair)

    response = client.get("/auth/disconnect-corp", follow_redirects=False)
    assert response.status_code in (302, 307)

    settings_response = client.get("/settings")
    assert settings_response.status_code == 200
    assert "Connect corporation data" in settings_response.text
    assert "Disconnect" not in settings_response.text


@respx.mock
def test_settings_shows_not_connected_by_default(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Connect corporation data" in response.text


@respx.mock
def test_settings_shows_per_source_permission_status(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    _connect_corp(client, test_settings, rsa_key_pair)

    respx.get(f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/").mock(
        return_value=Response(200, json={"name": "Test Corp"})
    )
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/assets", params={"page": 1}
    ).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "1"},
            json=[
                {
                    "item_id": 1,
                    "type_id": TRITANIUM_TYPE_ID,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 100,
                    "is_singleton": False,
                }
            ],
        )
    )
    # No Director role: blueprints 403s.
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/blueprints",
        params={"page": 1},
    ).mock(return_value=Response(403, json={"error": "Character does not have required role(s)"}))
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/industry/jobs",
        params={"page": 1},
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))

    response = client.get("/settings")

    assert response.status_code == 200
    assert "Connected &middot; 1 found" in response.text
    assert "No permission &mdash; requires the Director role" in response.text


@respx.mock
async def test_assets_list_merges_corp_assets(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    _connect_corp(client, test_settings, rsa_key_pair)

    await mongo_db.sde_types.insert_one(
        {"_id": TRITANIUM_TYPE_ID, "name": "Tritanium", "group_id": 18, "published": True}
    )

    respx.get(
        f"{test_settings.esi_base_url}/characters/{CHARACTER_ID}/assets", params={"page": 1}
    ).mock(return_value=Response(200, headers={"X-Pages": "1"}, json=[]))
    respx.get(
        f"{test_settings.esi_base_url}/corporations/{CORPORATION_ID}/assets", params={"page": 1}
    ).mock(
        return_value=Response(
            200,
            headers={"X-Pages": "1"},
            json=[
                {
                    "item_id": 1,
                    "type_id": TRITANIUM_TYPE_ID,
                    "location_id": 60003760,
                    "location_flag": "Hangar",
                    "location_type": "station",
                    "quantity": 250,
                    "is_singleton": False,
                }
            ],
        )
    )

    response = client.get("/assets")

    assert response.status_code == 200
    assert "Includes corporation assets" in response.text
    assert "250" in response.text
