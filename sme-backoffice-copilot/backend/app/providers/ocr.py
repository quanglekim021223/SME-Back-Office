"""OCR provider interface and shared OCR result contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OCRProviderRunContext(BaseModel):
    """Execution context passed to OCR provider calls."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    workflow_run_id: UUID | None = None
    correlation_id: str | None = None


class OCRExtractionMode(StrEnum):
    """OCR output modes a provider may support."""

    TEXT = "text"
    LAYOUT = "layout"
    TABLES = "tables"


class OCRRequestOptions(BaseModel):
    """Provider-neutral OCR extraction options."""

    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=list)
    extraction_modes: list[OCRExtractionMode] = Field(
        default_factory=lambda: [OCRExtractionMode.TEXT]
    )
    page_limit: int | None = Field(default=None, ge=1)
    preserve_layout: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class OCRInput(BaseModel):
    """Provider-neutral OCR input reference."""

    model_config = ConfigDict(extra="forbid")

    artifact_uri: str = Field(min_length=1)
    media_type: str | None = None
    content_hash: str | None = None
    local_path: str | None = None
    options: OCRRequestOptions = Field(default_factory=OCRRequestOptions)
    metadata: dict[str, object] = Field(default_factory=dict)


class OCRTextBlock(BaseModel):
    """One text block returned by an OCR provider."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    page_number: int = Field(default=1, ge=1)
    bounding_box: list[float] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)


class OCRResult(BaseModel):
    """Normalized OCR output shared by mock and real OCR providers."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    provider_version: str | None = None
    language: str | None = None
    full_text: str
    text_blocks: list[OCRTextBlock] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class OCRProvider(Protocol):
    """Protocol every OCR provider adapter should implement."""

    @property
    def name(self) -> str:
        """Return the stable provider name."""

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Extract text and layout information from a document artifact."""
