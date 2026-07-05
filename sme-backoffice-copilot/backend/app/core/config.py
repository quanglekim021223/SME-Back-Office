"""Typed application configuration loaded from environment variables."""

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class OCRProviderType(StrEnum):
    """Supported OCR provider selections."""

    MOCK = "mock"
    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    CHANDRAOCR = "chandraocr"


class LLMProviderType(StrEnum):
    """Supported LLM provider selections."""

    MOCK = "mock"
    OLLAMA = "ollama"
    OPENAI = "openai"


class WorkflowOrchestrationMode(StrEnum):
    """Supported workflow orchestration engines."""

    CUSTOM = "custom"
    LANGGRAPH = "langgraph"


class TracingBackendType(StrEnum):
    """Supported trace export backends."""

    DISABLED = "disabled"
    LANGFUSE = "langfuse"
    LANGSMITH = "langsmith"


class Settings(BaseSettings):
    """Environment-backed settings shared by backend infrastructure."""

    app_name: str = "SME Back-Office Copilot API"
    app_env: str = "local"
    app_debug: bool = False
    app_api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://sme:sme@localhost:5433/sme_backoffice"
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
    workflow_orchestration_mode: WorkflowOrchestrationMode = (
        WorkflowOrchestrationMode.CUSTOM
    )
    langgraph_checkpointing_enabled: bool = False
    langgraph_recursion_limit: int = 25
    tracing_backend: TracingBackendType = TracingBackendType.DISABLED
    tracing_project_name: str = "sme-backoffice-copilot-local"
    tracing_redaction_enabled: bool = True
    tracing_max_payload_chars: int = 4000
    langfuse_host: str = "http://localhost:3001"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "sme-backoffice-copilot-local"
    provider_timeout_seconds: float = 30.0
    provider_max_retries: int = 1
    provider_retry_backoff_seconds: float = 0.0
    llm_input_cost_per_1k_tokens_usd: Decimal = Decimal("0.00")
    llm_output_cost_per_1k_tokens_usd: Decimal = Decimal("0.00")
    provider_allow_cloud: bool = False
    provider_allow_sensitive_cloud_payloads: bool = False
    provider_require_deidentified_cloud_evaluation: bool = True
    provider_redaction_max_chars: int = 4000
    tesseract_binary_path: str = "tesseract"
    tesseract_language: str = "eng"
    paddleocr_language: str = "en"
    chandraocr_language: str = "en"
    # Image preprocessing pipeline (runs before OCR for all local engines)
    ocr_preprocessing_enabled: bool = False
    ocr_preprocessing_deskew: bool = True
    ocr_preprocessing_denoise: bool = False
    ocr_preprocessing_binarize: bool = False
    ocr_preprocessing_upscale_min_px: int = 0
    ocr_preprocessing_clahe_clip_limit: float = 2.0
    ocr_preprocessing_clahe_tile_grid_size: int = 8

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.2"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.30.69:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=(
            PROJECT_ROOT / ".env",
            BACKEND_ROOT / ".env",
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one immutable configuration view per process."""

    return Settings()
