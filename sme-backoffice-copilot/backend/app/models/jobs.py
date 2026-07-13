"""Durable queue jobs and transactional outbox records."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.models.workflow import WorkflowRun

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class WorkflowJobStatus(StrEnum):
    """Durable delivery and execution states for one workflow job."""

    QUEUED = "queued"
    PUBLISHED = "published"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"
    LOST = "lost"


class OutboxEventStatus(StrEnum):
    """Transactional outbox delivery states."""

    PENDING = "pending"
    PUBLISHED = "published"
    CANCELLED = "cancelled"


class WorkflowJob(
    TenantOwnedMixin,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    """Durable execution record keyed one-to-one by workflow run."""

    __tablename__ = "workflow_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            name="uq_workflow_jobs_workflow_run_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_workflow_jobs_idempotency_key",
        ),
        Index(
            "ix_workflow_jobs_stale_lease",
            "status",
            "lease_expires_at",
        ),
    )

    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_run: Mapped[WorkflowRun] = relationship("WorkflowRun")
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=WorkflowJobStatus.QUEUED.value,
        index=True,
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    command: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxEvent(
    TenantOwnedMixin,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    """Event committed atomically with business state and published later."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_dispatch",
            "status",
            "available_at",
        ),
    )

    workflow_job_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    workflow_job: Mapped[WorkflowJob] = relationship("WorkflowJob")
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=OutboxEventStatus.PENDING.value,
        index=True,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
