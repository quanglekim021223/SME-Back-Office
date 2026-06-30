"""Accounting classification and reconciliation ORM models."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
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
    from app.models.banking import Transaction
    from app.models.invoice import Invoice, InvoiceLineItem


class CategoryType(StrEnum):
    """High-level accounting category families."""

    REVENUE = "revenue"
    EXPENSE = "expense"
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    OTHER = "other"


class ClassificationTargetType(StrEnum):
    """Supported records that can receive a classification proposal."""

    INVOICE = "invoice"
    INVOICE_LINE_ITEM = "invoice_line_item"
    TRANSACTION = "transaction"


class ClassificationProposalStatus(StrEnum):
    """Classification proposal lifecycle states."""

    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReconciliationStatus(StrEnum):
    """Reconciliation lifecycle states."""

    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReconciliationMatchType(StrEnum):
    """Shape of a reconciliation match."""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    MANUAL = "manual"


class ReconciliationAllocationStatus(StrEnum):
    """Allocation lifecycle states."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class Category(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-specific accounting category used for classification and reporting."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_categories_tenant_slug"),
    )

    parent_category_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    category_type: Mapped[str] = mapped_column(
        String(64),
        default=CategoryType.OTHER.value,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    parent_category: Mapped[Category | None] = relationship(
        remote_side="Category.id",
        back_populates="child_categories",
    )
    child_categories: Mapped[list[Category]] = relationship(
        back_populates="parent_category"
    )
    classification_proposals: Mapped[list[ClassificationProposal]] = relationship(
        back_populates="proposed_category"
    )


class ClassificationProposal(
    TenantOwnedMixin,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    """Versioned proposal to classify an invoice, invoice line item, or transaction."""

    __tablename__ = "classification_proposals"

    proposed_category_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    invoice_line_item_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoice_line_items.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    supersedes_proposal_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("classification_proposals.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=ClassificationProposalStatus.PROPOSED.value,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    policy_flags: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    proposed_category: Mapped[Category | None] = relationship(
        back_populates="classification_proposals"
    )
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="classification_proposals"
    )
    invoice_line_item: Mapped[InvoiceLineItem | None] = relationship(
        back_populates="classification_proposals"
    )
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="classification_proposals"
    )
    supersedes_proposal: Mapped[ClassificationProposal | None] = relationship(
        remote_side="ClassificationProposal.id",
        back_populates="superseded_by_proposals",
    )
    superseded_by_proposals: Mapped[list[ClassificationProposal]] = relationship(
        back_populates="supersedes_proposal"
    )


class Reconciliation(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Versioned match proposal or decision connecting invoices to transactions."""

    __tablename__ = "reconciliations"

    supersedes_reconciliation_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("reconciliations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=ReconciliationStatus.PROPOSED.value,
        nullable=False,
    )
    match_type: Mapped[str] = mapped_column(
        String(64),
        default=ReconciliationMatchType.ONE_TO_ONE.value,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    invoice_total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    transaction_total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    difference_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    supersedes_reconciliation: Mapped[Reconciliation | None] = relationship(
        remote_side="Reconciliation.id",
        back_populates="superseded_by_reconciliations",
    )
    superseded_by_reconciliations: Mapped[list[Reconciliation]] = relationship(
        back_populates="supersedes_reconciliation"
    )
    allocations: Mapped[list[ReconciliationAllocation]] = relationship(
        back_populates="reconciliation",
        cascade="all, delete-orphan",
    )


class ReconciliationAllocation(
    TenantOwnedMixin,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    """Allocated amount linking one invoice record to one transaction record."""

    __tablename__ = "reconciliation_allocations"

    reconciliation_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("reconciliations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    invoice_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    transaction_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=ReconciliationAllocationStatus.PROPOSED.value,
        nullable=False,
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    allocation_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    reconciliation: Mapped[Reconciliation] = relationship(back_populates="allocations")
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="reconciliation_allocations"
    )
    transaction: Mapped[Transaction | None] = relationship(
        back_populates="reconciliation_allocations"
    )
