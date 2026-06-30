"""Invoice extraction and evidence ORM models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, UniqueConstraint
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
    from app.models.document import Document, DocumentArtifact, ProcessingRun


class InvoiceDirection(StrEnum):
    """Business direction of an invoice for SME accounting."""

    PAYABLE = "payable"
    RECEIVABLE = "receivable"
    UNKNOWN = "unknown"


class InvoiceStatus(StrEnum):
    """Invoice lifecycle states."""

    EXTRACTED = "extracted"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class Invoice(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured invoice header extracted from a source document."""

    __tablename__ = "invoices"

    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_processing_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("processing_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    supersedes_invoice_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=InvoiceStatus.EXTRACTED.value,
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(64),
        default=InvoiceDirection.UNKNOWN.value,
        nullable=False,
    )
    invoice_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_tax_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_tax_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    subtotal_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    tax_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped[Document | None] = relationship(back_populates="invoices")
    source_processing_run: Mapped[ProcessingRun | None] = relationship(
        back_populates="invoices"
    )
    supersedes_invoice: Mapped[Invoice | None] = relationship(
        remote_side="Invoice.id",
        back_populates="superseded_by_invoices",
    )
    superseded_by_invoices: Mapped[list[Invoice]] = relationship(
        back_populates="supersedes_invoice"
    )
    line_items: Mapped[list[InvoiceLineItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    field_evidence: Mapped[list[InvoiceFieldEvidence]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )


class InvoiceLineItem(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Structured line item extracted from an invoice table/grid."""

    __tablename__ = "invoice_line_items"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "line_number",
            name="uq_invoice_line_items_invoice_line_number",
        ),
    )

    invoice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_price_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
    field_evidence: Mapped[list[InvoiceFieldEvidence]] = relationship(
        back_populates="line_item"
    )


class InvoiceFieldEvidence(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Traceable source evidence for extracted invoice fields."""

    __tablename__ = "invoice_field_evidence"

    invoice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    line_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoice_line_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("document_artifacts.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    bounding_box: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    text_span: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    source_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    invoice: Mapped[Invoice] = relationship(back_populates="field_evidence")
    line_item: Mapped[InvoiceLineItem | None] = relationship(
        back_populates="field_evidence"
    )
    document: Mapped[Document | None] = relationship()
    artifact: Mapped[DocumentArtifact | None] = relationship()
