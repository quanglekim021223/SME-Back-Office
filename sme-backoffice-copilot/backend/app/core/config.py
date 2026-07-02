"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class OCRProviderType(StrEnum):
    """Supported OCR provider selections."""

    MOCK = "mock"
    TESSERACT = "tesseract"


class LLMProviderType(StrEnum):
    """Supported LLM provider selections."""

    MOCK = "mock"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    """Environment-backed settings shared by backend infrastructure."""

    app_name: str = "SME Back-Office Copilot API"
    app_env: str = "local"
    app_debug: bool = False
    app_api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://sme:sme@localhost:5432/sme_backoffice"
    database_echo: bool = False
    upload_storage_root: str = "../data/uploads"
    upload_max_size_bytes: int = 20 * 1024 * 1024
    upload_allowed_mime_types: list[str] = [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/csv",
    ]
    ocr_provider: OCRProviderType = OCRProviderType.MOCK
    llm_provider: LLMProviderType = LLMProviderType.MOCK
    provider_timeout_seconds: float = 30.0
    tesseract_binary_path: str = "tesseract"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
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
