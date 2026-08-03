"""API contracts for document workflow execution lineage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LineageCorrectionSignal(BaseModel):
    """Structured QA correction attached to a retry edge."""

    model_config = ConfigDict(extra="forbid")

    code: str
    target_agent: str
    message: str
    field_path: str | None = None
    instruction: str | None = None
    retryable: bool = True


class LineageStep(BaseModel):
    """One durable agent execution in workflow order."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=1)
    step_execution_id: UUID
    agent_name: str
    status: str
    attempt: int = Field(ge=1)
    started_at: datetime
    finished_at: datetime
    duration_ms: float | None = Field(default=None, ge=0)
    confidence: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    correction_signal: LineageCorrectionSignal | None = None


class LineageHandoff(BaseModel):
    """Directed edge recorded between two workflow nodes."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: UUID
    source_agent: str
    target_agent: str
    handoff_type: str
    status: str
    attempt: int = Field(ge=1)
    confidence: str | None = None
    occurred_at: datetime
    correction_signal: LineageCorrectionSignal | None = None


class LineageAuditEvent(BaseModel):
    """Human review action associated with the document workflow."""

    model_config = ConfigDict(extra="forbid")

    audit_event_id: UUID
    action: str
    actor_type: str
    actor_id: str | None = None
    actor_name: str | None = None
    occurred_at: datetime
    comment: str | None = None
    reason_code: str | None = None


class WorkflowLineageResponse(BaseModel):
    """Complete execution lineage for a document's latest workflow run."""

    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    workflow_run_id: UUID
    workflow_name: str
    workflow_version: str
    status: str
    stage: str | None = None
    total_latency_ms: float
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    steps: list[LineageStep] = Field(default_factory=list)
    handoffs: list[LineageHandoff] = Field(default_factory=list)
    audit_history: list[LineageAuditEvent] = Field(default_factory=list)
