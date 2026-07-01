"""Workflow and agent orchestration ORM models."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
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
    from app.models.document import ProcessingRun


class WorkflowRunStatus(StrEnum):
    """Workflow run lifecycle states."""

    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class AgentStepStatus(StrEnum):
    """Agent step lifecycle states."""

    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYING = "retrying"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    SKIPPED = "skipped"


class HandoffStatus(StrEnum):
    """Agent handoff lifecycle states."""

    CREATED = "created"
    CONSUMED = "consumed"

    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class WorkflowRun(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable state for one multi-agent workflow execution."""

    __tablename__ = "workflow_runs"

    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    processing_run_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("processing_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    workflow_name: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=WorkflowRunStatus.QUEUED.value,
        nullable=False,
    )
    current_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_run: Mapped[ProcessingRun | None] = relationship(
        back_populates="workflow_runs"
    )
    step_executions: Mapped[list[AgentStepExecution]] = relationship(
        back_populates="workflow_run",
        cascade="all, delete-orphan",
    )
    handoffs: Mapped[list[AgentHandoff]] = relationship(
        back_populates="workflow_run",
        cascade="all, delete-orphan",
    )


class AgentDefinition(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    """Versioned registry entry for a bounded agent role."""

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint(
            "agent_name",
            "agent_version",
            name="uq_agent_definitions_name_version",
        ),
    )

    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_schema_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_schema_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_tools: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    retry_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    step_executions: Mapped[list[AgentStepExecution]] = relationship(
        back_populates="agent_definition"
    )


class AgentStepExecution(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable record of one agent invocation."""

    __tablename__ = "agent_step_executions"

    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    agent_definition_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=AgentStepStatus.SCHEDULED.value,
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="step_executions")
    agent_definition: Mapped[AgentDefinition | None] = relationship(
        back_populates="step_executions"
    )
    outgoing_handoffs: Mapped[list[AgentHandoff]] = relationship(
        back_populates="source_step",
        cascade="all, delete-orphan",
        foreign_keys="AgentHandoff.source_step_execution_id",
    )


class AgentHandoff(TenantOwnedMixin, UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Versioned envelope passed between agents."""

    __tablename__ = "agent_handoffs"

    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_step_execution_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("agent_step_executions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    target_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    handoff_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(64),
        default=HandoffStatus.CREATED.value,
        nullable=False,
    )
    payload_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    evidence_refs: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_flags: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)

    workflow_run: Mapped[WorkflowRun] = relationship(back_populates="handoffs")
    source_step: Mapped[AgentStepExecution | None] = relationship(
        back_populates="outgoing_handoffs",
        foreign_keys=[source_step_execution_id],
    )
