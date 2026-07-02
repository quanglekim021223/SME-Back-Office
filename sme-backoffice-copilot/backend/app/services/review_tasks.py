"""Application service for read-only review task queries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast
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
from app.review import (
    ReviewAction,
    SupersedableRecord,
    SupersessionPlan,
    build_classification_supersession_plan,
    build_invoice_extraction_supersession_plan,
    build_reconciliation_supersession_plan,
    mark_record_superseded,
)
from app.validation import parse_decimal, parse_iso_date


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


@dataclass(frozen=True)
class ReviewTaskCorrectionResult:
    """Result returned after a review correction creates a new resource version."""

    action: ReviewAction
    review_task: ReviewTask
    resource_type: str
    superseded_resource_id: UUID
    replacement_resource_id: UUID
    replacement_resource_status: str
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


class InvalidReviewCorrectionError(ReviewTaskDecisionError):
    """Raised when correction input cannot be applied safely."""


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

    def add_invoice(self, invoice: Invoice) -> Invoice:
        """Stage a replacement invoice for insertion."""

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        """Stage a replacement classification proposal for insertion."""

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        """Stage a replacement reconciliation for insertion."""

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

    def add_invoice(self, invoice: Invoice) -> Invoice:
        """Stage a replacement invoice for insertion."""

        self.session.add(invoice)
        return invoice

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        """Stage a replacement classification proposal for insertion."""

        self.session.add(proposal)
        return proposal

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        """Stage a replacement reconciliation for insertion."""

        self.session.add(reconciliation)
        return reconciliation

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

    async def correct_extracted_fields(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        actor: Principal,
        corrected_fields: dict[str, object],
        comment: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewTaskCorrectionResult:
        """Correct extracted invoice fields by creating a new invoice version."""

        return await self._correct(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            action=ReviewAction.CORRECT_EXTRACTION,
            actor=actor,
            corrected_payload=corrected_fields,
            comment=comment,
            reason_code=reason_code,
            correlation_id=correlation_id,
        )

    async def correct_classification(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        actor: Principal,
        corrected_fields: dict[str, object],
        comment: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewTaskCorrectionResult:
        """Correct a classification proposal by creating a new version."""

        return await self._correct(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            action=ReviewAction.CORRECT_CLASSIFICATION,
            actor=actor,
            corrected_payload=corrected_fields,
            comment=comment,
            reason_code=reason_code,
            correlation_id=correlation_id,
        )

    async def correct_reconciliation(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        actor: Principal,
        corrected_fields: dict[str, object],
        comment: str | None = None,
        reason_code: str | None = None,
        correlation_id: str | None = None,
    ) -> ReviewTaskCorrectionResult:
        """Correct a reconciliation proposal by creating a new version."""

        return await self._correct(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            action=ReviewAction.CORRECT_RECONCILIATION,
            actor=actor,
            corrected_payload=corrected_fields,
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

    async def _correct(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
        action: ReviewAction,
        actor: Principal,
        corrected_payload: dict[str, object],
        comment: str | None,
        reason_code: str | None,
        correlation_id: str | None,
    ) -> ReviewTaskCorrectionResult:
        """Apply a correction by superseding the old resource with a new version."""

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
        plan = build_correction_supersession_plan(
            resource=resource,
            action=action,
        )
        before_state = {
            "review_task": review_task_audit_state(task),
            "resource": review_resource_audit_state(resource),
        }

        replacement_resource = create_corrected_resource(
            resource=resource,
            plan=plan,
            corrected_payload=corrected_payload,
        )
        mark_record_superseded(cast(SupersedableRecord, resource.record), plan)
        add_replacement_resource(self.persistence, replacement_resource)
        update_review_task_target(task=task, replacement_resource=replacement_resource)

        now = utc_now()
        task.status = ReviewTaskStatus.RESOLVED.value
        task.resolved_at = now
        task.resolved_by_user_id = parse_optional_uuid(actor.user_id)

        replacement_reviewable_resource = ReviewableResource(
            resource_type=resource.resource_type,
            resource_id=get_resource_id(replacement_resource),
            record=replacement_resource,
        )
        after_state = {
            "review_task": review_task_audit_state(task),
            "superseded_resource": review_resource_audit_state(resource),
            "replacement_resource": review_resource_audit_state(
                replacement_reviewable_resource
            ),
        }
        audit_event = AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=parse_optional_uuid(actor.user_id),
            actor_type=AuditActorType.USER.value,
            severity=AuditEventSeverity.INFO.value,
            action=review_action_to_audit_action(action),
            resource_type=resource.resource_type,
            resource_id=get_resource_id(replacement_resource),
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
                "superseded_resource_id": str(resource.resource_id),
                "replacement_resource_id": str(get_resource_id(replacement_resource)),
                "corrected_fields": corrected_payload,
            },
        )
        self.persistence.add_audit_event(audit_event)
        await self.persistence.flush()
        await self.persistence.commit()

        return ReviewTaskCorrectionResult(
            action=action,
            review_task=task,
            resource_type=resource.resource_type,
            superseded_resource_id=resource.resource_id,
            replacement_resource_id=get_resource_id(replacement_resource),
            replacement_resource_status=get_resource_status(replacement_resource),
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


def build_correction_supersession_plan(
    *,
    resource: ReviewableResource,
    action: ReviewAction,
) -> SupersessionPlan:
    """Build a supersession plan for a supported correction action."""

    if (
        isinstance(resource.record, Invoice)
        and action == ReviewAction.CORRECT_EXTRACTION
    ):
        return build_invoice_extraction_supersession_plan(resource.record)
    if (
        isinstance(resource.record, ClassificationProposal)
        and action == ReviewAction.CORRECT_CLASSIFICATION
    ):
        return build_classification_supersession_plan(resource.record)
    if (
        isinstance(resource.record, Reconciliation)
        and action == ReviewAction.CORRECT_RECONCILIATION
    ):
        return build_reconciliation_supersession_plan(resource.record)
    raise UnsupportedReviewActionError(
        "Review task resource does not support this correction action."
    )


def create_corrected_resource(
    *,
    resource: ReviewableResource,
    plan: SupersessionPlan,
    corrected_payload: dict[str, object],
) -> Invoice | ClassificationProposal | Reconciliation:
    """Create a corrected replacement resource from the old resource."""

    if isinstance(resource.record, Invoice):
        return create_corrected_invoice(
            current=resource.record,
            plan=plan,
            corrected_fields=corrected_payload,
        )
    if isinstance(resource.record, ClassificationProposal):
        return create_corrected_classification_proposal(
            current=resource.record,
            plan=plan,
            corrected_fields=corrected_payload,
        )
    if isinstance(resource.record, Reconciliation):
        return create_corrected_reconciliation(
            current=resource.record,
            plan=plan,
            corrected_fields=corrected_payload,
        )
    raise UnsupportedReviewActionError("Unsupported correction resource.")


def create_corrected_invoice(
    *,
    current: Invoice,
    plan: SupersessionPlan,
    corrected_fields: dict[str, object],
) -> Invoice:
    """Create a new corrected invoice version."""

    replacement = Invoice(
        id=uuid4(),
        tenant_id=current.tenant_id,
        document_id=current.document_id,
        source_processing_run_id=current.source_processing_run_id,
        supersedes_invoice_id=current.id,
        version=plan.new_version,
        status=plan.new_record_status,
        direction=current.direction,
        invoice_number=current.invoice_number,
        supplier_name=current.supplier_name,
        supplier_tax_id=current.supplier_tax_id,
        customer_name=current.customer_name,
        customer_tax_id=current.customer_tax_id,
        issue_date=current.issue_date,
        due_date=current.due_date,
        currency=current.currency,
        subtotal_amount=current.subtotal_amount,
        tax_amount=current.tax_amount,
        total_amount=current.total_amount,
        confidence=current.confidence,
        notes=current.notes,
    )
    apply_invoice_field_corrections(replacement, corrected_fields)
    return replacement


def create_corrected_classification_proposal(
    *,
    current: ClassificationProposal,
    plan: SupersessionPlan,
    corrected_fields: dict[str, object],
) -> ClassificationProposal:
    """Create a new corrected classification proposal version."""

    replacement = ClassificationProposal(
        id=uuid4(),
        tenant_id=current.tenant_id,
        proposed_category_id=current.proposed_category_id,
        invoice_id=current.invoice_id,
        invoice_line_item_id=current.invoice_line_item_id,
        transaction_id=current.transaction_id,
        supersedes_proposal_id=current.id,
        target_type=current.target_type,
        status=plan.new_record_status,
        version=plan.new_version,
        confidence=current.confidence,
        source_agent=current.source_agent,
        source_agent_version=current.source_agent_version,
        rationale=current.rationale,
        evidence_refs=current.evidence_refs,
        policy_flags=current.policy_flags,
        metadata_=current.metadata_,
    )
    apply_classification_corrections(replacement, corrected_fields)
    return replacement


def create_corrected_reconciliation(
    *,
    current: Reconciliation,
    plan: SupersessionPlan,
    corrected_fields: dict[str, object],
) -> Reconciliation:
    """Create a new corrected reconciliation version."""

    replacement = Reconciliation(
        id=uuid4(),
        tenant_id=current.tenant_id,
        supersedes_reconciliation_id=current.id,
        status=plan.new_record_status,
        match_type=current.match_type,
        version=plan.new_version,
        currency=current.currency,
        invoice_total_amount=current.invoice_total_amount,
        transaction_total_amount=current.transaction_total_amount,
        difference_amount=current.difference_amount,
        confidence=current.confidence,
        source_agent=current.source_agent,
        source_agent_version=current.source_agent_version,
        rationale=current.rationale,
        evidence_refs=current.evidence_refs,
        metadata_=current.metadata_,
    )
    apply_reconciliation_corrections(replacement, corrected_fields)
    return replacement


def apply_invoice_field_corrections(
    invoice: Invoice,
    corrected_fields: dict[str, object],
) -> None:
    """Apply allowed invoice field corrections to a replacement invoice."""

    allowed_fields = {
        "direction",
        "invoice_number",
        "supplier_name",
        "supplier_tax_id",
        "customer_name",
        "customer_tax_id",
        "issue_date",
        "due_date",
        "currency",
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "confidence",
        "notes",
    }
    unknown_fields = set(corrected_fields) - allowed_fields
    if unknown_fields:
        raise InvalidReviewCorrectionError(
            f"Unsupported invoice correction fields: {sorted(unknown_fields)}"
        )

    for field_name, value in corrected_fields.items():
        if field_name in {"issue_date", "due_date"}:
            setattr(invoice, field_name, parse_iso_date(value))
        elif field_name in {"subtotal_amount", "tax_amount", "total_amount"}:
            setattr(invoice, field_name, parse_decimal(value))
        else:
            setattr(invoice, field_name, value)


def apply_classification_corrections(
    proposal: ClassificationProposal,
    corrected_fields: dict[str, object],
) -> None:
    """Apply allowed classification corrections to a replacement proposal."""

    allowed_fields = {
        "proposed_category_id",
        "confidence",
        "rationale",
        "evidence_refs",
        "policy_flags",
        "metadata",
    }
    unknown_fields = set(corrected_fields) - allowed_fields
    if unknown_fields:
        raise InvalidReviewCorrectionError(
            f"Unsupported classification correction fields: {sorted(unknown_fields)}"
        )

    for field_name, value in corrected_fields.items():
        if field_name == "metadata":
            proposal.metadata_ = cast(dict[str, object] | None, value)
        else:
            setattr(proposal, field_name, value)


def apply_reconciliation_corrections(
    reconciliation: Reconciliation,
    corrected_fields: dict[str, object],
) -> None:
    """Apply allowed reconciliation corrections to a replacement record."""

    allowed_fields = {
        "match_type",
        "currency",
        "invoice_total_amount",
        "transaction_total_amount",
        "difference_amount",
        "confidence",
        "rationale",
        "evidence_refs",
        "metadata",
    }
    unknown_fields = set(corrected_fields) - allowed_fields
    if unknown_fields:
        raise InvalidReviewCorrectionError(
            f"Unsupported reconciliation correction fields: {sorted(unknown_fields)}"
        )

    for field_name, value in corrected_fields.items():
        if field_name in {
            "invoice_total_amount",
            "transaction_total_amount",
            "difference_amount",
        }:
            setattr(reconciliation, field_name, coerce_decimal(value))
        elif field_name == "metadata":
            reconciliation.metadata_ = cast(dict[str, object] | None, value)
        else:
            setattr(reconciliation, field_name, value)


def add_replacement_resource(
    persistence: ReviewTaskDecisionPersistence,
    replacement: Invoice | ClassificationProposal | Reconciliation,
) -> None:
    """Stage a corrected replacement resource for persistence."""

    if isinstance(replacement, Invoice):
        persistence.add_invoice(replacement)
    elif isinstance(replacement, ClassificationProposal):
        persistence.add_classification_proposal(replacement)
    elif isinstance(replacement, Reconciliation):
        persistence.add_reconciliation(replacement)
    else:
        raise UnsupportedReviewActionError("Unsupported replacement resource.")


def update_review_task_target(
    *,
    task: ReviewTask,
    replacement_resource: Invoice | ClassificationProposal | Reconciliation,
) -> None:
    """Point the resolved review task at the corrected replacement resource."""

    if isinstance(replacement_resource, Invoice):
        task.invoice_id = replacement_resource.id
    elif isinstance(replacement_resource, ClassificationProposal):
        task.classification_proposal_id = replacement_resource.id
    elif isinstance(replacement_resource, Reconciliation):
        task.reconciliation_id = replacement_resource.id


def get_resource_id(
    resource: Invoice | ClassificationProposal | Reconciliation,
) -> UUID:
    """Return id from a supported corrected resource."""

    return resource.id


def get_resource_status(
    resource: Invoice | ClassificationProposal | Reconciliation,
) -> str:
    """Return status from a supported corrected resource."""

    return resource.status


def coerce_decimal(value: object) -> Decimal | None:
    """Coerce request values into Decimal for money fields."""

    return parse_decimal(value)


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
    if action == ReviewAction.CORRECT_EXTRACTION:
        return "review_task.extraction_corrected"
    if action == ReviewAction.CORRECT_CLASSIFICATION:
        return "review_task.classification_corrected"
    if action == ReviewAction.CORRECT_RECONCILIATION:
        return "review_task.reconciliation_corrected"
    return f"review_task.{action.value}"


def parse_optional_uuid(value: str | None) -> UUID | None:
    """Parse a UUID string when possible."""

    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
