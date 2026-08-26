from dataclasses import dataclass
from time import monotonic
from typing import Any

import httpx
from prometheus_client import Counter, Histogram

from app.core.config import Settings

_STATION_ID_MAX = 64_000_000_000

ESI_REQUEST_DURATION = Histogram(
    "eve_build_esi_request_duration_seconds", "ESI HTTP request duration", ["endpoint"]
)
ESI_REQUEST_ERRORS = Counter(
    "eve_build_esi_request_errors_total", "ESI HTTP requests that raised an error", ["endpoint"]
)


async def _timed_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    endpoint: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    start = monotonic()
    try:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response
    except httpx.HTTPError:
        ESI_REQUEST_ERRORS.labels(endpoint=endpoint).inc()
        raise
    finally:
        ESI_REQUEST_DURATION.labels(endpoint=endpoint).observe(monotonic() - start)


@dataclass(frozen=True)
class BlueprintEntry:
    item_id: int
    type_id: int
    location_id: int
    location_flag: str
    quantity: int
    runs: int
    material_efficiency: int
    time_efficiency: int


@dataclass(frozen=True)
class AssetEntry:
    item_id: int
    type_id: int
    location_id: int
    location_flag: str
    location_type: str
    quantity: int
    is_singleton: bool


@dataclass(frozen=True)
class IndustryJobEntry:
    job_id: int
    activity_id: int
    blueprint_type_id: int
    product_type_id: int | None
    facility_id: int
    runs: int
    status: str
    start_date: str
    end_date: str


def _headers(settings: Settings, access_token: str | None) -> dict[str, str]:
    headers = {
        "X-Compatibility-Date": settings.esi_compatibility_date,
        "User-Agent": settings.esi_user_agent,
    }
    if access_token is not None:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


async def _get_all_pages(
    settings: Settings, access_token: str, path: str, *, endpoint: str
) -> list[dict[str, Any]]:
    url = f"{settings.esi_base_url}{path}"
    headers = _headers(settings, access_token)

    async with httpx.AsyncClient() as client:
        first_response = await _timed_get(
            client, url, endpoint=endpoint, params={"page": 1}, headers=headers
        )
        results: list[dict[str, Any]] = list(first_response.json())
        total_pages = int(first_response.headers.get("X-Pages", "1"))

        for page in range(2, total_pages + 1):
            response = await _timed_get(
                client, url, endpoint=endpoint, params={"page": page}, headers=headers
            )
            results.extend(response.json())

    return results


async def get_character_blueprints(
    settings: Settings, access_token: str, character_id: int
) -> list[BlueprintEntry]:
    raw_entries = await _get_all_pages(
        settings,
        access_token,
        f"/characters/{character_id}/blueprints",
        endpoint="characters/blueprints",
    )
    return [
        BlueprintEntry(
            item_id=entry["item_id"],
            type_id=entry["type_id"],
            location_id=entry["location_id"],
            location_flag=entry["location_flag"],
            quantity=entry["quantity"],
            runs=entry["runs"],
            material_efficiency=entry["material_efficiency"],
            time_efficiency=entry["time_efficiency"],
        )
        for entry in raw_entries
    ]


async def get_character_assets(
    settings: Settings, access_token: str, character_id: int
) -> list[AssetEntry]:
    raw_entries = await _get_all_pages(
        settings,
        access_token,
        f"/characters/{character_id}/assets",
        endpoint="characters/assets",
    )
    return [
        AssetEntry(
            item_id=entry["item_id"],
            type_id=entry["type_id"],
            location_id=entry["location_id"],
            location_flag=entry["location_flag"],
            location_type=entry["location_type"],
            quantity=entry["quantity"],
            is_singleton=entry["is_singleton"],
        )
        for entry in raw_entries
    ]


async def get_character_industry_jobs(
    settings: Settings, access_token: str, character_id: int
) -> list[IndustryJobEntry]:
    url = f"{settings.esi_base_url}/characters/{character_id}/industry/jobs"
    headers = _headers(settings, access_token)

    async with httpx.AsyncClient() as client:
        response = await _timed_get(
            client, url, endpoint="characters/industry_jobs", headers=headers
        )

    return [
        IndustryJobEntry(
            job_id=entry["job_id"],
            activity_id=entry["activity_id"],
            blueprint_type_id=entry["blueprint_type_id"],
            product_type_id=entry.get("product_type_id"),
            facility_id=entry["facility_id"],
            runs=entry["runs"],
            status=entry["status"],
            start_date=entry["start_date"],
            end_date=entry["end_date"],
        )
        for entry in response.json()
    ]


@dataclass(frozen=True)
class MarketPriceEntry:
    type_id: int
    adjusted_price: float | None
    average_price: float | None


async def get_market_prices(settings: Settings) -> list[MarketPriceEntry]:
    url = f"{settings.esi_base_url}/markets/prices"
    headers = _headers(settings, None)

    async with httpx.AsyncClient() as client:
        response = await _timed_get(client, url, endpoint="markets/prices", headers=headers)

    return [
        MarketPriceEntry(
            type_id=entry["type_id"],
            adjusted_price=entry.get("adjusted_price"),
            average_price=entry.get("average_price"),
        )
        for entry in response.json()
    ]


async def get_location_name(settings: Settings, access_token: str, location_id: int) -> str | None:
    if location_id < _STATION_ID_MAX:
        path = f"/universe/stations/{location_id}"
        headers = _headers(settings, None)
        endpoint = "universe/stations"
    else:
        path = f"/universe/structures/{location_id}"
        headers = _headers(settings, access_token)
        endpoint = "universe/structures"

    async with httpx.AsyncClient() as client:
        try:
            response = await _timed_get(
                client, f"{settings.esi_base_url}{path}", endpoint=endpoint, headers=headers
            )
        except httpx.HTTPStatusError:
            return None

    name = response.json().get("name")
    return name if isinstance(name, str) else None
