"""Shared workflow contracts for controlled multi-agent orchestration."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStateStatus(StrEnum):
    """Runtime workflow lifecycle states used by workflow state snapshots."""

    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class WorkflowStage(StrEnum):
    """High-level stages in the document processing workflow."""

    INGESTED = "ingested"
    DOCUMENT_INTAKE = "document_intake"
    PRIVACY_POLICY_GATE = "privacy_policy_gate"
    LAYOUT_ANALYSIS = "layout_analysis"
    METADATA_EXTRACTION = "metadata_extraction"
    TABLE_EXTRACTION = "table_extraction"
    TOTALS_EXTRACTION = "totals_extraction"
    INVOICE_ASSEMBLY = "invoice_assembly"
    QA_VALIDATION = "qa_validation"
    CLASSIFICATION = "classification"
    RECONCILIATION = "reconciliation"
    REVIEW_COORDINATION = "review_coordination"
    INSIGHT_GENERATION = "insight_generation"
    COMPLETED = "completed"
    FAILED = "failed"


class ConfidenceLevel(StrEnum):
    """Coarse confidence labels shared by agents, tools, and handoffs."""

    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class HandoffType(StrEnum):
    """Agent handoff categories."""

    CONTROL = "control"
    DATA = "data"
    CORRECTION = "correction"
    REVIEW = "review"
    FAILURE = "failure"


class QAErrorSeverity(StrEnum):
    """Severity labels for deterministic or model-assisted QA findings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class CorrectionAction(StrEnum):
    """Recommended action for targeted self-correction."""

    RE_EXTRACT_FIELD = "re_extract_field"
    RE_EXTRACT_TABLE = "re_extract_table"
    RECALCULATE_TOTALS = "recalculate_totals"
    SEND_TO_REVIEW = "send_to_review"
    BLOCK_WORKFLOW = "block_workflow"


class WorkflowArtifactRef(BaseModel):
    """Stable reference to an original or derived workflow artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    media_type: str | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class QACorrectionTarget(BaseModel):
    """Specific target that should receive a QA correction signal."""

    model_config = ConfigDict(extra="forbid")

    target_agent: str = Field(min_length=1)
    action: CorrectionAction
    field_path: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    instruction: str = Field(min_length=1)


class QAErrorSignal(BaseModel):
    """Structured QA signal for targeted self-correction loops."""

    model_config = ConfigDict(extra="forbid")

    signal_id: UUID = Field(default_factory=uuid4)
    schema_version: str = "qa-error-signal.v1"
    code: str = Field(min_length=1, pattern=r"^[A-Z0-9_]+$")
    severity: QAErrorSeverity
    message: str = Field(min_length=1)
    source_agent: str = Field(min_length=1)
    correction_target: QACorrectionTarget | None = None
    expected_value: object | None = None
    observed_value: object | None = None
    context: dict[str, object] = Field(default_factory=dict)
    retryable: bool = True


class AgentHandoffEnvelope(BaseModel):
    """Versioned envelope used when one agent hands work to another agent."""

    model_config = ConfigDict(extra="forbid")

    handoff_id: UUID = Field(default_factory=uuid4)
    schema_version: str = "agent-handoff.v1"
    tenant_id: UUID
    document_id: UUID
    workflow_run_id: UUID | None = None
    source_agent: str = Field(min_length=1)
    target_agent: str = Field(min_length=1)
    handoff_type: HandoffType
    stage: WorkflowStage
    payload: dict[str, object] = Field(default_factory=dict)
    payload_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    qa_error_signal: QAErrorSignal | None = None
    policy_flags: dict[str, object] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)


class WorkflowState(BaseModel):
    """Shared state snapshot carried through the multi-agent workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "workflow-state.v1"
    tenant_id: UUID
    document_id: UUID
    document_type: str = Field(min_length=1)
    workflow_run_id: UUID | None = None
    processing_run_id: UUID | None = None
    status: WorkflowStateStatus = WorkflowStateStatus.QUEUED
    stage: WorkflowStage = WorkflowStage.INGESTED
    current_agent: str | None = None
    completed_agents: list[str] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    max_retries: int = Field(default=3, ge=0)
    artifacts: dict[str, WorkflowArtifactRef] = Field(default_factory=dict)
    latest_handoff: AgentHandoffEnvelope | None = None
    qa_error_signals: list[QAErrorSignal] = Field(default_factory=list)
    policy_flags: dict[str, object] = Field(default_factory=dict)
    scratchpad: dict[str, object] = Field(default_factory=dict)
