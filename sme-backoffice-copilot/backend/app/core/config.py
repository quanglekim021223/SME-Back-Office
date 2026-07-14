"""Typed application configuration loaded from environment variables."""

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class OCRProviderType(StrEnum):
    """Supported OCR provider selections."""

    MOCK = "mock"
    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    CHANDRAOCR = "chandraocr"
    AZURE_DI = "azure_di"


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


class LogFormat(StrEnum):
    """Supported application log formats."""

    PRETTY = "pretty"
    JSON = "json"


class WorkflowQueueMode(StrEnum):
    """Runtime used to execute accepted document workflow jobs."""

    IN_PROCESS = "in_process"
    CELERY = "celery"


class DocumentStorageProvider(StrEnum):
    """Durable storage backends for original uploaded documents."""

    LOCAL = "local"
    AZURE_BLOB = "azure_blob"


class Settings(BaseSettings):
    """Environment-backed settings shared by backend infrastructure."""

    app_name: str = "SME Back-Office Copilot API"
    app_env: str = "local"
    app_debug: bool = False
    app_api_prefix: str = "/api/v1"
    log_format: LogFormat = LogFormat.PRETTY
    database_url: str = "postgresql+asyncpg://sme:sme@localhost:5433/sme_backoffice"
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=2, ge=0)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    workflow_queue_mode: WorkflowQueueMode = WorkflowQueueMode.IN_PROCESS
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_worker_concurrency: int = Field(default=2, ge=1)
    celery_task_max_retries: int = Field(default=3, ge=0)
    celery_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    outbox_dispatcher_enabled: bool = True
    outbox_poll_interval_seconds: float = Field(default=0.5, gt=0)
    outbox_batch_size: int = Field(default=50, ge=1)
    outbox_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    workflow_job_heartbeat_seconds: float = Field(default=10.0, gt=0)
    workflow_job_lease_seconds: float = Field(default=45.0, gt=0)
    provider_rate_limit_enabled: bool = False
    provider_rate_limit_redis_url: str = "redis://localhost:6379/2"
    provider_ocr_requests_per_second: int = Field(default=5, ge=1)
    provider_llm_requests_per_second: int = Field(default=5, ge=1)
    provider_rate_limit_wait_timeout_seconds: float = Field(default=30.0, gt=0)
    document_storage_provider: DocumentStorageProvider = DocumentStorageProvider.LOCAL
    upload_storage_root: str = "../data/uploads"
    upload_max_size_bytes: int = 20 * 1024 * 1024
    upload_allowed_mime_types: list[str] = [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/csv",
    ]
    azure_storage_blob_endpoint: str = ""
    azure_storage_container: str = "documents"
    azure_storage_connection_string: str = ""
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
    azure_di_endpoint: str = ""
    azure_di_key: str = ""
    # Azure Document Intelligence model selection.
    # Use "prebuilt-layout" for raw OCR (default, backward-compatible).
    # Use "prebuilt-invoice" to enable the structured extraction fast-path,
    # which pre-populates invoice extraction groups directly from Azure DI
    # without calling the LLM for metadata/table/totals, reducing latency
    # from ~45 s to ~5–8 s.
    azure_di_model_id: str = "prebuilt-layout"
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

    @model_validator(mode="after")
    def validate_hosted_transport_security(self) -> Self:
        """Reject plaintext hosted database and Redis connections early."""

        if self.app_env.lower() == "local":
            return self

        redis_settings = [
            ("CELERY_BROKER_URL", self.celery_broker_url),
            ("CELERY_RESULT_BACKEND", self.celery_result_backend),
        ]
        if self.provider_rate_limit_enabled:
            redis_settings.append(
                ("PROVIDER_RATE_LIMIT_REDIS_URL", self.provider_rate_limit_redis_url)
            )
        for setting_name, value in redis_settings:
            if not value.startswith("rediss://"):
                raise ValueError(
                    f"{setting_name} must use a rediss:// URL outside local."
                )

        query = parse_qs(urlsplit(self.database_url).query)
        tls_values = query.get("ssl", []) + query.get("sslmode", [])
        if not any(
            value.lower() in {"require", "verify-ca", "verify-full", "true"}
            for value in tls_values
        ):
            raise ValueError(
                "DATABASE_URL must require TLS with ssl=require outside local."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable configuration view per process."""

    return Settings()
