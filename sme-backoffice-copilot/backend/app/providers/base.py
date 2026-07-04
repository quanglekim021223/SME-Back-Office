"""Provider-neutral AI adapter contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProviderCapability(StrEnum):
    """High-level capabilities a provider adapter can expose."""

    LLM_GENERATION = "llm_generation"
    OCR_EXTRACTION = "ocr_extraction"
    DOCUMENT_PARSING = "document_parsing"
    STRUCTURED_OUTPUT = "structured_output"


class ProviderDeploymentMode(StrEnum):
    """Where provider inference is executed."""

    MOCK = "mock"
    LOCAL = "local"
    CLOUD = "cloud"


class ProviderHealthStatus(StrEnum):
    """Provider health-check result states."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AIProviderMetadata(BaseModel):
    """Stable provider descriptor used by routing and observability."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    deployment_mode: ProviderDeploymentMode
    capabilities: set[ProviderCapability] = Field(default_factory=set)
    default_model: str | None = None
    supports_streaming: bool = False
    supports_structured_output: bool = False
    is_cloud_provider: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class AIProviderRunContext(BaseModel):
    """Shared context passed to provider adapters."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID | None = None
    workflow_run_id: UUID | None = None
    agent_name: str | None = None
    correlation_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ProviderHealthCheck(BaseModel):
    """Normalized provider health-check response."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    status: ProviderHealthStatus
    latency_ms: int | None = Field(default=None, ge=0)
    message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class AIProvider(Protocol):
    """Protocol shared by OCR, LLM, and future AI provider adapters."""

    @property
    def name(self) -> str:
        """Return the stable provider name."""

    @property
    def metadata(self) -> AIProviderMetadata:
        """Return provider routing and observability metadata."""

    async def health_check(self) -> ProviderHealthCheck:
        """Return a lightweight provider health check."""
