import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from tests.test_blueprints_routes import CHARACTER_ID, _log_in

JOB_ID = 42
BLUEPRINT_TYPE_ID = 588
PRODUCT_TYPE_ID = 587
FACILITY_ID = 60003760


def _mock_jobs(settings: Settings) -> None:
    respx.get(f"{settings.esi_base_url}/characters/{CHARACTER_ID}/industry/jobs").mock(
        return_value=Response(
            200,
            json=[
                {
                    "job_id": JOB_ID,
                    "installer_id": CHARACTER_ID,
                    "facility_id": FACILITY_ID,
                    "station_id": FACILITY_ID,
                    "activity_id": 1,
                    "blueprint_id": 100,
                    "blueprint_type_id": BLUEPRINT_TYPE_ID,
                    "product_type_id": PRODUCT_TYPE_ID,
                    "blueprint_location_id": FACILITY_ID,
                    "output_location_id": FACILITY_ID,
                    "runs": 3,
                    "status": "active",
                    "duration": 1200,
                    "start_date": "2026-01-01T00:00:00Z",
                    "end_date": "2026-01-01T01:00:00Z",
                }
            ],
        )
    )


async def _seed_types(mongo_db: AsyncMongoMockClient) -> None:
    await mongo_db.sde_types.insert_many(
        [
            {
                "_id": BLUEPRINT_TYPE_ID,
                "name": "Rifter Blueprint",
                "group_id": 1,
                "published": True,
            },
            {"_id": PRODUCT_TYPE_ID, "name": "Rifter", "group_id": 25, "published": True},
        ]
    )


@respx.mock
async def test_job_detail_shows_blueprint_location_and_product(
    client: TestClient,
    test_settings: Settings,
    mongo_db: AsyncMongoMockClient,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    await _seed_types(mongo_db)
    _mock_jobs(test_settings)
    respx.get(f"{test_settings.esi_base_url}/universe/stations/{FACILITY_ID}").mock(
        return_value=Response(200, json={"name": "Jita IV - Moon 4"})
    )

    response = client.get(f"/jobs/{JOB_ID}")

    assert response.status_code == 200
    assert "Rifter Blueprint" in response.text
    assert "Manufacturing" in response.text
    assert "Jita IV - Moon 4" in response.text
    assert "Rifter" in response.text
    assert ">3<" in response.text
    assert "mini-gauge" in response.text


@respx.mock
async def test_job_detail_404_for_unknown_job(
    client: TestClient,
    test_settings: Settings,
    rsa_key_pair: tuple[rsa.RSAPrivateKey, dict[str, object]],
) -> None:
    _log_in(client, test_settings, rsa_key_pair)
    _mock_jobs(test_settings)

    response = client.get("/jobs/999999")

    assert response.status_code == 404
