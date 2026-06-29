"""Document, artifact, and processing run ORM models."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.models.organization import Organization


class DocumentType(StrEnum):
    """Supported source document families."""

    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    OTHER = "other"


class DocumentStatus(StrEnum):
    """Document lifecycle states."""

    UPLOADED = "uploaded"
    SCANNING = "scanning"
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    PROCESSED = "processed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    """Document artifact types."""

    ORIGINAL = "original"
    RENDERED_PAGE = "rendered_page"
    OCR_TEXT = "ocr_text"
    TABLE_CROP = "table_crop"
    STRUCTURED_OUTPUT = "structured_output"


class ProcessingRunStatus(StrEnum):
    """Processing run lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Document(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable source document metadata owned by one tenant."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "content_hash", name="uq_documents_tenant_hash"),
    )

    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=DocumentStatus.UPLOADED.value,
        nullable=False,
    )
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship()
    artifacts: Mapped[list[DocumentArtifact]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    processing_runs: Mapped[list[ProcessingRun]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentArtifact(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Object-storage reference for original and derived document artifacts."""

    __tablename__ = "document_artifacts"

    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    document: Mapped[Document] = relationship(back_populates="artifacts")


class ProcessingRun(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Reproducible execution metadata for document processing."""

    __tablename__ = "processing_runs"

    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=ProcessingRunStatus.QUEUED.value,
        nullable=False,
    )
    workflow_name: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    document: Mapped[Document] = relationship(back_populates="processing_runs")
