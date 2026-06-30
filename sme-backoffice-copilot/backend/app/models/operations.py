"""Human review, insight, and audit trail ORM models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    utc_now,
)

if TYPE_CHECKING:
    from app.models.accounting import ClassificationProposal, Reconciliation
    from app.models.banking import Transaction
    from app.models.document import Document
    from app.models.invoice import Invoice
    from app.models.user import User
    from app.models.workflow import WorkflowRun


class InsightStatus(StrEnum):
    """Insight lifecycle states."""

    GENERATED = "generated"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


class InsightType(StrEnum):
    """High-level business insight families."""

    CASHFLOW = "cashflow"
    REVENUE = "revenue"
    EXPENSE = "expense"
    RECONCILIATION = "reconciliation"
    RISK = "risk"
    OPPORTUNITY = "opportunity"
    OTHER = "other"


class InsightSeverity(StrEnum):
    """Business severity for generated insights."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewTaskStatus(StrEnum):
    """Human review task lifecycle states."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ReviewTaskType(StrEnum):
    """Supported human review task families."""

    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"
    RECONCILIATION = "reconciliation"
    POLICY = "policy"
    INSIGHT = "insight"
    OTHER = "other"


class ReviewTaskPriority(StrEnum):
    """Human review task priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ReviewTargetType(StrEnum):
    """Supported target records for human review."""

    DOCUMENT = "document"
    INVOICE = "invoice"
    TRANSACTION = "transaction"
    CLASSIFICATION_PROPOSAL = "classification_proposal"
    RECONCILIATION = "reconciliation"
    INSIGHT = "insight"
    OTHER = "other"


class AuditActorType(StrEnum):
    """Actor families that can emit audit events."""

    USER = "user"
    SYSTEM = "system"
    AGENT = "agent"
    SERVICE = "service"


class AuditEventSeverity(StrEnum):
    """Operational severity for audit events."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Insight(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Actionable business insight generated from financial data."""

    __tablename__ = "insights"

    source_workflow_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    supersedes_insight_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("insights.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=InsightStatus.GENERATED.value,
        nullable=False,
    )
    insight_type: Mapped[str] = mapped_column(
        String(64),
        default=InsightType.OTHER.value,
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(64),
        default=InsightSeverity.INFO.value,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    estimated_impact_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    source_workflow_run: Mapped[WorkflowRun | None] = relationship()
    supersedes_insight: Mapped[Insight | None] = relationship(
        remote_side="Insight.id",
        back_populates="superseded_by_insights",
    )
    superseded_by_insights: Mapped[list[Insight]] = relationship(
        back_populates="supersedes_insight"
    )
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="insight")


class ReviewTask(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Human-in-the-loop task for reviewing uncertain or policy-sensitive outputs."""

    __tablename__ = "review_tasks"

    assigned_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
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
    classification_proposal_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("classification_proposals.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    reconciliation_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("reconciliations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    insight_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("insights.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    task_type: Mapped[str] = mapped_column(
        String(64),
        default=ReviewTaskType.OTHER.value,
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(64),
        default=ReviewTargetType.OTHER.value,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        default=ReviewTaskStatus.OPEN.value,
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(
        String(64),
        default=ReviewTaskPriority.NORMAL.value,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    assigned_user: Mapped[User | None] = relationship(foreign_keys=[assigned_user_id])
    resolved_by_user: Mapped[User | None] = relationship(
        foreign_keys=[resolved_by_user_id]
    )
    workflow_run: Mapped[WorkflowRun | None] = relationship()
    document: Mapped[Document | None] = relationship()
    invoice: Mapped[Invoice | None] = relationship()
    transaction: Mapped[Transaction | None] = relationship()
    classification_proposal: Mapped[ClassificationProposal | None] = relationship()
    reconciliation: Mapped[Reconciliation | None] = relationship()
    insight: Mapped[Insight | None] = relationship(back_populates="review_tasks")


class AuditEvent(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-oriented audit event for security, compliance, and traceability."""

    __tablename__ = "audit_events"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(
        String(64),
        default=AuditActorType.SYSTEM.value,
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(64),
        default=AuditEventSeverity.INFO.value,
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    after_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    metadata_: Mapped[dict[str, object] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

    actor_user: Mapped[User | None] = relationship()
