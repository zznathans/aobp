from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    eve_sso_client_id: str = ""
    eve_sso_callback_url: str = ""
    eve_sso_scopes: str = ""
    eve_sso_authorize_url: str = "https://login.eveonline.com/v2/oauth/authorize"
    eve_sso_token_url: str = "https://login.eveonline.com/v2/oauth/token"
    eve_sso_jwks_url: str = "https://login.eveonline.com/oauth/jwks"
    eve_sso_issuer: str = "https://login.eveonline.com"
    eve_sso_audience: str = "EVE Online"

    esi_base_url: str = "https://esi.evetech.net"
    esi_compatibility_date: str = "2026-08-18"
    esi_user_agent: str = "aobp"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "aobp"

    sde_data_dir: str = "app/data/sde"
    run_migrations_on_startup: bool = True

    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl_seconds: int = 60 * 60 * 24

    session_secret_key: str = "insecure-dev-secret-change-me"
    session_cookie_name: str = "aobp_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14


@lru_cache
def get_settings() -> Settings:
    return Settings()
