"""Application service for read-only review task queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal
from app.models.accounting import (
    ClassificationProposal,
    ClassificationProposalStatus,
    Reconciliation,
    ReconciliationStatus,
)
from app.models.base import utc_now
from app.models.invoice import Invoice, InvoiceStatus
from app.models.operations import (
    AuditActorType,
    AuditEvent,
    AuditEventSeverity,
    Insight,
    InsightStatus,
    ReviewTargetType,
    ReviewTask,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.repositories.review_tasks import ReviewTaskRepository
from app.review import ReviewAction


@dataclass(frozen=True)
class ReviewTaskListResult:
    """Review task list query result."""

    tasks: list[ReviewTask]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class ReviewTaskDecisionResult:
    """Result returned after approving or rejecting a review task proposal."""

    action: ReviewAction
    review_task: ReviewTask
    resource_type: str
    resource_id: UUID
    resource_status: str
    audit_event: AuditEvent


class ReviewTaskDecisionError(Exception):
    """Base error for review task decision failures."""


class ReviewTaskNotFoundError(ReviewTaskDecisionError):
    """Raised when a review task is not found for the tenant."""


class ReviewTaskNotActionableError(ReviewTaskDecisionError):
    """Raised when a review task can no longer be approved or rejected."""


class ReviewResourceNotFoundError(ReviewTaskDecisionError):
    """Raised when the task's target proposal/resource cannot be found."""


class UnsupportedReviewActionError(ReviewTaskDecisionError):
    """Raised when a task does not support approve/reject decisions."""


class ReviewTaskDecisionPersistence(Protocol):
    """Persistence boundary used by review decision actions."""

    async def get_review_task_for_tenant(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        """Return one tenant-owned review task."""

    async def get_invoice_for_tenant(
        self,
        *,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> Invoice | None:
        """Return one tenant-owned invoice."""

    async def get_classification_proposal_for_tenant(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
    ) -> ClassificationProposal | None:
        """Return one tenant-owned classification proposal."""

    async def get_reconciliation_for_tenant(
        self,
        *,
        tenant_id: UUID,
        reconciliation_id: UUID,
    ) -> Reconciliation | None:
        """Return one tenant-owned reconciliation."""

    async def get_insight_for_tenant(
        self,
        *,
        tenant_id: UUID,
        insight_id: UUID,
    ) -> Insight | None:
        """Return one tenant-owned insight."""

    def add_audit_event(self, audit_event: AuditEvent) -> AuditEvent:
        """Stage an audit event for insertion."""

    async def flush(self) -> None:
        """Flush staged persistence changes."""

    async def commit(self) -> None:
        """Commit staged persistence changes."""


class SqlAlchemyReviewTaskDecisionPersistence:
    """SQLAlchemy-backed persistence adapter for review decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.review_task_repository = ReviewTaskRepository(session)

    async def get_review_task_for_tenant(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        """Return one tenant-owned review task."""

        return await self.review_task_repository.get_for_tenant(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
        )

    async def get_invoice_for_tenant(
        self,
        *,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> Invoice | None:
        """Return one tenant-owned invoice."""

        statement = select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.id == invoice_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_classification_proposal_for_tenant(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
    ) -> ClassificationProposal | None:
        """Return one tenant-owned classification proposal."""

        statement = select(ClassificationProposal).where(
            ClassificationProposal.tenant_id == tenant_id,
            ClassificationProposal.id == proposal_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_reconciliation_for_tenant(
        self,
        *,
        tenant_id: UUID,
        reconciliation_id: UUID,
    ) -> Reconciliation | None:
        """Return one tenant-owned reconciliation."""

        statement = select(Reconciliation).where(
            Reconciliation.tenant_id == tenant_id,
            Reconciliation.id == reconciliation_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_insight_for_tenant(
        self,
        *,
        tenant_id: UUID,
        insight_id: UUID,
    ) -> Insight | None:
        """Return one tenant-owned insight."""

        statement = select(Insight).where(
            Insight.tenant_id == tenant_id,
            Insight.id == insight_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def add_audit_event(self, audit_event: AuditEvent) -> AuditEvent:
        """Stage an audit event for insertion."""

        self.session.add(audit_event)
        return audit_event

    async def flush(self) -> None:
        """Flush staged changes."""

        await self.session.flush()

    async def commit(self) -> None:
        """Commit staged changes."""

        await self.session.commit()


class ReviewTaskQueryService:
    """Read-only service for tenant-scoped review tasks."""

    def __init__(self, repository: ReviewTaskRepository) -> None:
        self.repository = repository

    @classmethod
    def from_session(cls, session: AsyncSession) -> ReviewTaskQueryService:
        """Create the service from a SQLAlchemy session."""

        return cls(repository=ReviewTaskRepository(session))

    async def list_review_tasks(
        self,
        *,
        tenant_id: UUID,
        status_filter: ReviewTaskStatus | None = None,
        task_type: ReviewTaskType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewTaskListResult:
        """Return review tasks for one tenant."""

        tasks, total = await self.repository.list_for_tenant(
            tenant_id=tenant_id,
            status_filter=status_filter,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
        return ReviewTaskListResult(
            tasks=tasks,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_review_task(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        """Return one tenant-owned review task by id."""

        return await self.repository.get_for_tenant(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
        )


class ReviewTaskDecisionService:
    """Service for approving and rejecting review task proposals."""

    def __init__(self, persistence: ReviewTaskDecisionPersistence) -> None:
        self.persistence = persistence

    @classmethod
    def from_session(cls, session: AsyncSession) -> ReviewTaskDecisionService:
        """Create the service from a SQLAlchemy session."""

        return cls(
            persistence=SqlAlchemyReviewTaskDecisionPersistence(session),
        )

    async def approve_review_task(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        actor: Principal,
        comment: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewTaskDecisionResult:
        """Approve a review task's proposal and record an audit event."""

        return await self._decide(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            action=ReviewAction.APPROVE_PROPOSAL,
            actor=actor,
            comment=comment,
            reason_code=reason_code,
            correlation_id=correlation_id,
        )

    async def reject_review_task(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        actor: Principal,
        comment: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewTaskDecisionResult:
        """Reject a review task's proposal and record an audit event."""

        return await self._decide(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            action=ReviewAction.REJECT_PROPOSAL,
            actor=actor,
            comment=comment,
            reason_code=reason_code,
            correlation_id=correlation_id,
        )

    async def _decide(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        action: ReviewAction,
        actor: Principal,
        comment: str | None,
        reason_code: str | None,
        correlation_id: str | None,
    ) -> ReviewTaskDecisionResult:
        """Apply a review decision, resolve the task, and append audit data."""

        task = await self.persistence.get_review_task_for_tenant(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
        )
        if task is None:
            raise ReviewTaskNotFoundError("Review task was not found.")
        if task.status not in {
            ReviewTaskStatus.OPEN.value,
            ReviewTaskStatus.IN_PROGRESS.value,
        }:
            raise ReviewTaskNotActionableError(
                "Review task is not open or in progress."
            )

        resource = await self._load_reviewable_resource(
            tenant_id=tenant_id,
            task=task,
        )
        before_state = {
            "review_task": review_task_audit_state(task),
            "resource": review_resource_audit_state(resource),
        }
        resource_status = apply_resource_decision(resource=resource, action=action)

        now = utc_now()
        task.status = ReviewTaskStatus.RESOLVED.value
        task.resolved_at = now
        task.resolved_by_user_id = parse_optional_uuid(actor.user_id)

        after_state = {
            "review_task": review_task_audit_state(task),
            "resource": review_resource_audit_state(resource),
        }
        audit_event = AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=parse_optional_uuid(actor.user_id),
            actor_type=AuditActorType.USER.value,
            severity=AuditEventSeverity.INFO.value,
            action=review_action_to_audit_action(action),
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            correlation_id=correlation_id,
            before_state=before_state,
            after_state=after_state,
            metadata_={
                "review_task_id": str(task.id),
                "review_task_type": task.task_type,
                "review_target_type": task.target_type,
                "actor_subject": actor.subject,
                "comment": comment,
                "reason_code": reason_code,
            },
        )
        self.persistence.add_audit_event(audit_event)
        await self.persistence.flush()
        await self.persistence.commit()

        return ReviewTaskDecisionResult(
            action=action,
            review_task=task,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            resource_status=resource_status,
            audit_event=audit_event,
        )

    async def _load_reviewable_resource(
        self,
        *,
        tenant_id: UUID,
        task: ReviewTask,
    ) -> ReviewableResource:
        """Load the concrete resource linked to a review task."""

        if task.target_type == ReviewTargetType.INVOICE.value and task.invoice_id:
            invoice = await self.persistence.get_invoice_for_tenant(
                tenant_id=tenant_id,
                invoice_id=task.invoice_id,
            )
            if invoice is None:
                raise ReviewResourceNotFoundError("Linked invoice was not found.")
            return ReviewableResource(
                resource_type=ReviewTargetType.INVOICE.value,
                resource_id=invoice.id,
                record=invoice,
            )
        if (
            task.target_type == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
            and task.classification_proposal_id
        ):
            proposal = await self.persistence.get_classification_proposal_for_tenant(
                tenant_id=tenant_id,
                proposal_id=task.classification_proposal_id,
            )
            if proposal is None:
                raise ReviewResourceNotFoundError(
                    "Linked classification proposal was not found."
                )
            return ReviewableResource(
                resource_type=ReviewTargetType.CLASSIFICATION_PROPOSAL.value,
                resource_id=proposal.id,
                record=proposal,
            )
        if (
            task.target_type == ReviewTargetType.RECONCILIATION.value
            and task.reconciliation_id
        ):
            reconciliation = await self.persistence.get_reconciliation_for_tenant(
                tenant_id=tenant_id,
                reconciliation_id=task.reconciliation_id,
            )
            if reconciliation is None:
                raise ReviewResourceNotFoundError(
                    "Linked reconciliation was not found."
                )
            return ReviewableResource(
                resource_type=ReviewTargetType.RECONCILIATION.value,
                resource_id=reconciliation.id,
                record=reconciliation,
            )
        if task.target_type == ReviewTargetType.INSIGHT.value and task.insight_id:
            insight = await self.persistence.get_insight_for_tenant(
                tenant_id=tenant_id,
                insight_id=task.insight_id,
            )
            if insight is None:
                raise ReviewResourceNotFoundError("Linked insight was not found.")
            return ReviewableResource(
                resource_type=ReviewTargetType.INSIGHT.value,
                resource_id=insight.id,
                record=insight,
            )
        raise UnsupportedReviewActionError(
            "Review task does not link to an approve/reject resource."
        )


@dataclass(frozen=True)
class ReviewableResource:
    """Concrete resource being approved or rejected through a review task."""

    resource_type: str
    resource_id: UUID
    record: object


def apply_resource_decision(
    *,
    resource: ReviewableResource,
    action: ReviewAction,
) -> str:
    """Apply approve/reject status to a supported reviewable resource."""

    if isinstance(resource.record, Invoice):
        status = (
            InvoiceStatus.APPROVED.value
            if action == ReviewAction.APPROVE_PROPOSAL
            else InvoiceStatus.REJECTED.value
        )
    elif isinstance(resource.record, ClassificationProposal):
        status = (
            ClassificationProposalStatus.APPROVED.value
            if action == ReviewAction.APPROVE_PROPOSAL
            else ClassificationProposalStatus.REJECTED.value
        )
    elif isinstance(resource.record, Reconciliation):
        status = (
            ReconciliationStatus.APPROVED.value
            if action == ReviewAction.APPROVE_PROPOSAL
            else ReconciliationStatus.REJECTED.value
        )
    elif isinstance(resource.record, Insight):
        status = (
            InsightStatus.PUBLISHED.value
            if action == ReviewAction.APPROVE_PROPOSAL
            else InsightStatus.DISMISSED.value
        )
    else:
        raise UnsupportedReviewActionError(
            "Unsupported review resource for approve/reject decision."
        )

    resource.record.status = status
    return status


def review_task_audit_state(task: ReviewTask) -> dict[str, object]:
    """Return a compact audit snapshot for a review task."""

    return {
        "id": str(task.id),
        "status": task.status,
        "task_type": task.task_type,
        "target_type": task.target_type,
        "resolved_at": task.resolved_at.isoformat()
        if task.resolved_at is not None
        else None,
        "resolved_by_user_id": str(task.resolved_by_user_id)
        if task.resolved_by_user_id is not None
        else None,
    }


def review_resource_audit_state(resource: ReviewableResource) -> dict[str, object]:
    """Return a compact audit snapshot for a reviewable resource."""

    return {
        "id": str(resource.resource_id),
        "resource_type": resource.resource_type,
        "status": getattr(resource.record, "status", None),
        "version": getattr(resource.record, "version", None),
    }


def review_action_to_audit_action(action: ReviewAction) -> str:
    """Return stable audit action names for review decisions."""

    if action == ReviewAction.APPROVE_PROPOSAL:
        return "review_task.approved"
    if action == ReviewAction.REJECT_PROPOSAL:
        return "review_task.rejected"
    return f"review_task.{action.value}"


def parse_optional_uuid(value: str | None) -> UUID | None:
    """Parse a UUID string when possible."""

    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
