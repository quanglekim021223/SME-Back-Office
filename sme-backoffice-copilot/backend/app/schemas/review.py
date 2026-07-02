"""Review task API schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.operations import ReviewTask


class ReviewTaskSummaryResponse(BaseModel):
    """Compact review task shape used by review queue list APIs."""

    id: UUID
    tenant_id: UUID
    task_type: str
    target_type: str
    status: str
    priority: str
    title: str
    reason_code: str | None = None
    due_at: datetime | None = None
    source_agent: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, task: ReviewTask) -> ReviewTaskSummaryResponse:
        """Build a list response from a ReviewTask ORM model."""

        return cls(
            id=task.id,
            tenant_id=task.tenant_id,
            task_type=task.task_type,
            target_type=task.target_type,
            status=task.status,
            priority=task.priority,
            title=task.title,
            reason_code=task.reason_code,
            due_at=task.due_at,
            source_agent=task.source_agent,
            evidence_refs=task.evidence_refs or [],
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class ReviewTaskDetailResponse(ReviewTaskSummaryResponse):
    """Detailed review task response for a single review task."""

    assigned_user_id: UUID | None = None
    resolved_by_user_id: UUID | None = None
    workflow_run_id: UUID | None = None
    document_id: UUID | None = None
    invoice_id: UUID | None = None
    transaction_id: UUID | None = None
    classification_proposal_id: UUID | None = None
    reconciliation_id: UUID | None = None
    insight_id: UUID | None = None
    description: str | None = None
    resolved_at: datetime | None = None
    source_agent_version: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_model(cls, task: ReviewTask) -> ReviewTaskDetailResponse:
        """Build a detail response from a ReviewTask ORM model."""

        summary = ReviewTaskSummaryResponse.from_model(task)
        return cls(
            **summary.model_dump(),
            assigned_user_id=task.assigned_user_id,
            resolved_by_user_id=task.resolved_by_user_id,
            workflow_run_id=task.workflow_run_id,
            document_id=task.document_id,
            invoice_id=task.invoice_id,
            transaction_id=task.transaction_id,
            classification_proposal_id=task.classification_proposal_id,
            reconciliation_id=task.reconciliation_id,
            insight_id=task.insight_id,
            description=task.description,
            resolved_at=task.resolved_at,
            source_agent_version=task.source_agent_version,
            metadata=task.metadata_ or {},
        )


class ReviewTaskListResponse(BaseModel):
    """Paginated review task list response."""

    items: list[ReviewTaskSummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ReviewTaskDecisionRequest(BaseModel):
    """Request body for approving or rejecting a review task proposal."""

    comment: str | None = Field(default=None, max_length=2000)
    reason_code: str | None = Field(default=None, max_length=128)


class ReviewTaskDecisionResponse(BaseModel):
    """Response returned after a review task decision action."""

    action: str
    review_task: ReviewTaskDetailResponse
    resource_type: str
    resource_id: UUID
    resource_status: str
    audit_event_id: UUID


class ExtractedFieldsCorrectionRequest(BaseModel):
    """Request body for correcting extracted invoice fields."""

    corrected_fields: dict[str, object] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)
    reason_code: str | None = Field(default=None, max_length=128)


class ClassificationCorrectionRequest(BaseModel):
    """Request body for correcting a classification proposal."""

    proposed_category_id: UUID | None = None
    confidence: str | None = Field(default=None, max_length=32)
    rationale: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] | None = None
    metadata: dict[str, object] | None = None
    comment: str | None = Field(default=None, max_length=2000)
    reason_code: str | None = Field(default=None, max_length=128)


class ReconciliationCorrectionRequest(BaseModel):
    """Request body for correcting a reconciliation proposal."""

    match_type: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    invoice_total_amount: Decimal | None = None
    transaction_total_amount: Decimal | None = None
    difference_amount: Decimal | None = None
    confidence: str | None = Field(default=None, max_length=32)
    rationale: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] | None = None
    metadata: dict[str, object] | None = None
    comment: str | None = Field(default=None, max_length=2000)
    reason_code: str | None = Field(default=None, max_length=128)


class ReviewTaskCorrectionResponse(BaseModel):
    """Response returned after a review correction creates a new version."""

    action: str
    review_task: ReviewTaskDetailResponse
    resource_type: str
    superseded_resource_id: UUID
    replacement_resource_id: UUID
    replacement_resource_status: str
    audit_event_id: UUID
