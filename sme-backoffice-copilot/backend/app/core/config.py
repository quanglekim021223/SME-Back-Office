"""Typed application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings shared by backend infrastructure."""

    app_name: str = "SME Back-Office Copilot API"
    app_env: str = "local"
    app_debug: bool = False
    app_api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://sme:sme@localhost:5432/sme_backoffice"
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable configuration view per process."""

    return Settings()
