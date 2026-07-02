from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.auth import Principal
from app.models.accounting import (
    ClassificationProposal,
    ClassificationProposalStatus,
    ClassificationTargetType,
    Reconciliation,
    ReconciliationStatus,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.operations import (
    AuditEvent,
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.review import ReviewAction
from app.services.review_tasks import (
    InvalidReviewCorrectionError,
    ReviewResourceNotFoundError,
    ReviewTaskDecisionService,
    ReviewTaskNotActionableError,
    ReviewTaskNotFoundError,
    UnsupportedReviewActionError,
)


class FakeDecisionPersistence:
    def __init__(
        self,
        *,
        tasks: list[ReviewTask] | None = None,
        proposals: list[ClassificationProposal] | None = None,
        reconciliations: list[Reconciliation] | None = None,
        invoices: list[Invoice] | None = None,
    ) -> None:
        self.tasks = tasks or []
        self.proposals = proposals or []
        self.reconciliations = reconciliations or []
        self.invoices = invoices or []
        self.audit_events: list[AuditEvent] = []
        self.flush_called = False
        self.commit_called = False

    async def get_review_task_for_tenant(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        return next(
            (
                task
                for task in self.tasks
                if task.tenant_id == tenant_id and task.id == review_task_id
            ),
            None,
        )

    async def get_invoice_for_tenant(
        self,
        *,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> Invoice | None:
        return next(
            (
                invoice
                for invoice in self.invoices
                if invoice.tenant_id == tenant_id and invoice.id == invoice_id
            ),
            None,
        )

    async def get_classification_proposal_for_tenant(
        self,
        *,
        tenant_id: UUID,
        proposal_id: UUID,
    ) -> ClassificationProposal | None:
        return next(
            (
                proposal
                for proposal in self.proposals
                if proposal.tenant_id == tenant_id and proposal.id == proposal_id
            ),
            None,
        )

    async def get_reconciliation_for_tenant(
        self,
        *,
        tenant_id: UUID,
        reconciliation_id: UUID,
    ) -> Reconciliation | None:
        return next(
            (
                reconciliation
                for reconciliation in self.reconciliations
                if reconciliation.tenant_id == tenant_id
                and reconciliation.id == reconciliation_id
            ),
            None,
        )

    async def get_insight_for_tenant(self, *, tenant_id: UUID, insight_id: UUID):
        del tenant_id, insight_id
        return None

    def add_invoice(self, invoice: Invoice) -> Invoice:
        self.invoices.append(invoice)
        return invoice

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        self.proposals.append(proposal)
        return proposal

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        self.reconciliations.append(reconciliation)
        return reconciliation

    def add_audit_event(self, audit_event: AuditEvent) -> AuditEvent:
        self.audit_events.append(audit_event)
        return audit_event

    async def flush(self) -> None:
        self.flush_called = True

    async def commit(self) -> None:
        self.commit_called = True


def principal(user_id: UUID | None = None) -> Principal:
    resolved_user_id = user_id or uuid4()
    return Principal(
        user_id=str(resolved_user_id),
        subject=str(resolved_user_id),
        is_authenticated=True,
    )


def build_review_task(
    *,
    tenant_id: UUID,
    target_type: ReviewTargetType,
    task_type: ReviewTaskType,
    invoice_id: UUID | None = None,
    classification_proposal_id: UUID | None = None,
    reconciliation_id: UUID | None = None,
    status: ReviewTaskStatus = ReviewTaskStatus.OPEN,
) -> ReviewTask:
    return ReviewTask(
        id=uuid4(),
        tenant_id=tenant_id,
        task_type=task_type.value,
        target_type=target_type.value,
        status=status.value,
        priority=ReviewTaskPriority.NORMAL.value,
        title="Review task",
        invoice_id=invoice_id,
        classification_proposal_id=classification_proposal_id,
        reconciliation_id=reconciliation_id,
    )


@pytest.mark.asyncio
async def test_approve_classification_proposal_resolves_task_and_writes_audit() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=tenant_id,
        target_type=ClassificationTargetType.TRANSACTION.value,
        status=ClassificationProposalStatus.PENDING_REVIEW.value,
        version=1,
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        task_type=ReviewTaskType.CLASSIFICATION,
        classification_proposal_id=proposal.id,
    )
    persistence = FakeDecisionPersistence(tasks=[task], proposals=[proposal])

    result = await ReviewTaskDecisionService(persistence).approve_review_task(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(actor_id),
        comment="Looks correct.",
        reason_code="APPROVED_BY_ACCOUNTANT",
        correlation_id="corr-123",
    )

    assert result.action == ReviewAction.APPROVE_PROPOSAL
    assert result.resource_type == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    assert result.resource_id == proposal.id
    assert result.resource_status == ClassificationProposalStatus.APPROVED.value
    assert proposal.status == ClassificationProposalStatus.APPROVED.value
    assert task.status == ReviewTaskStatus.RESOLVED.value
    assert task.resolved_by_user_id == actor_id
    assert task.resolved_at is not None
    assert persistence.flush_called is True
    assert persistence.commit_called is True

    audit_event = persistence.audit_events[0]
    assert audit_event.action == "review_task.approved"
    assert audit_event.tenant_id == tenant_id
    assert audit_event.actor_user_id == actor_id
    assert audit_event.resource_type == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    assert audit_event.resource_id == proposal.id
    assert audit_event.correlation_id == "corr-123"
    assert audit_event.before_state["resource"]["status"] == (
        ClassificationProposalStatus.PENDING_REVIEW.value
    )
    assert audit_event.after_state["resource"]["status"] == (
        ClassificationProposalStatus.APPROVED.value
    )
    assert audit_event.metadata_["comment"] == "Looks correct."
    assert audit_event.metadata_["reason_code"] == "APPROVED_BY_ACCOUNTANT"


@pytest.mark.asyncio
async def test_reject_reconciliation_resolves_task_and_writes_audit() -> None:
    tenant_id = uuid4()
    reconciliation = Reconciliation(
        id=uuid4(),
        tenant_id=tenant_id,
        status=ReconciliationStatus.PENDING_REVIEW.value,
        version=2,
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.RECONCILIATION,
        task_type=ReviewTaskType.RECONCILIATION,
        reconciliation_id=reconciliation.id,
    )
    persistence = FakeDecisionPersistence(
        tasks=[task],
        reconciliations=[reconciliation],
    )

    result = await ReviewTaskDecisionService(persistence).reject_review_task(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(),
        comment="Wrong transaction.",
        reason_code="WRONG_MATCH",
    )

    assert result.action == ReviewAction.REJECT_PROPOSAL
    assert result.resource_type == ReviewTargetType.RECONCILIATION.value
    assert result.resource_status == ReconciliationStatus.REJECTED.value
    assert reconciliation.status == ReconciliationStatus.REJECTED.value
    assert task.status == ReviewTaskStatus.RESOLVED.value
    assert persistence.audit_events[0].action == "review_task.rejected"
    assert persistence.audit_events[0].metadata_["reason_code"] == "WRONG_MATCH"


@pytest.mark.asyncio
async def test_correct_extracted_fields_supersedes_invoice_and_writes_audit() -> None:
    tenant_id = uuid4()
    invoice = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        status=InvoiceStatus.PENDING_REVIEW.value,
        version=1,
        invoice_number="INV-001",
        total_amount=Decimal("120.00"),
        currency="USD",
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.INVOICE,
        task_type=ReviewTaskType.EXTRACTION,
        invoice_id=invoice.id,
    )
    persistence = FakeDecisionPersistence(tasks=[task], invoices=[invoice])

    result = await ReviewTaskDecisionService(persistence).correct_extracted_fields(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(),
        corrected_fields={
            "total_amount": "110.00",
            "invoice_number": "INV-001-CORRECTED",
        },
        comment="Total was read incorrectly.",
        reason_code="OCR_TOTAL_FIX",
    )

    replacement = persistence.invoices[-1]
    assert result.action == ReviewAction.CORRECT_EXTRACTION
    assert result.superseded_resource_id == invoice.id
    assert result.replacement_resource_id == replacement.id
    assert result.replacement_resource_status == InvoiceStatus.EXTRACTED.value
    assert invoice.status == InvoiceStatus.SUPERSEDED.value
    assert replacement.supersedes_invoice_id == invoice.id
    assert replacement.version == 2
    assert replacement.total_amount == Decimal("110.00")
    assert replacement.invoice_number == "INV-001-CORRECTED"
    assert task.invoice_id == replacement.id
    assert task.status == ReviewTaskStatus.RESOLVED.value
    assert persistence.audit_events[0].action == "review_task.extraction_corrected"
    assert persistence.audit_events[0].metadata_["superseded_resource_id"] == str(
        invoice.id
    )
    assert persistence.audit_events[0].metadata_["replacement_resource_id"] == str(
        replacement.id
    )


@pytest.mark.asyncio
async def test_correct_classification_supersedes_old_proposal() -> None:
    tenant_id = uuid4()
    new_category_id = uuid4()
    proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=tenant_id,
        target_type=ClassificationTargetType.TRANSACTION.value,
        status=ClassificationProposalStatus.PENDING_REVIEW.value,
        version=3,
        rationale="Original rationale",
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        task_type=ReviewTaskType.CLASSIFICATION,
        classification_proposal_id=proposal.id,
    )
    persistence = FakeDecisionPersistence(tasks=[task], proposals=[proposal])

    result = await ReviewTaskDecisionService(persistence).correct_classification(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(),
        corrected_fields={
            "proposed_category_id": new_category_id,
            "confidence": "high",
            "rationale": "Corrected by accountant.",
            "evidence_refs": ["review:classification:manual"],
        },
    )

    replacement = persistence.proposals[-1]
    assert result.action == ReviewAction.CORRECT_CLASSIFICATION
    assert proposal.status == ClassificationProposalStatus.SUPERSEDED.value
    assert replacement.supersedes_proposal_id == proposal.id
    assert replacement.version == 4
    assert replacement.status == ClassificationProposalStatus.PROPOSED.value
    assert replacement.proposed_category_id == new_category_id
    assert replacement.confidence == "high"
    assert replacement.rationale == "Corrected by accountant."
    assert replacement.evidence_refs == ["review:classification:manual"]
    assert task.classification_proposal_id == replacement.id
    assert persistence.audit_events[0].action == "review_task.classification_corrected"


@pytest.mark.asyncio
async def test_correct_reconciliation_supersedes_old_reconciliation() -> None:
    tenant_id = uuid4()
    reconciliation = Reconciliation(
        id=uuid4(),
        tenant_id=tenant_id,
        status=ReconciliationStatus.PENDING_REVIEW.value,
        version=2,
        invoice_total_amount=Decimal("110.00"),
        transaction_total_amount=Decimal("100.00"),
        difference_amount=Decimal("10.00"),
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.RECONCILIATION,
        task_type=ReviewTaskType.RECONCILIATION,
        reconciliation_id=reconciliation.id,
    )
    persistence = FakeDecisionPersistence(
        tasks=[task],
        reconciliations=[reconciliation],
    )

    result = await ReviewTaskDecisionService(persistence).correct_reconciliation(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(),
        corrected_fields={
            "transaction_total_amount": Decimal("110.00"),
            "difference_amount": Decimal("0.00"),
            "confidence": "high",
        },
    )

    replacement = persistence.reconciliations[-1]
    assert result.action == ReviewAction.CORRECT_RECONCILIATION
    assert reconciliation.status == ReconciliationStatus.SUPERSEDED.value
    assert replacement.supersedes_reconciliation_id == reconciliation.id
    assert replacement.version == 3
    assert replacement.status == ReconciliationStatus.PROPOSED.value
    assert replacement.transaction_total_amount == Decimal("110.00")
    assert replacement.difference_amount == Decimal("0.00")
    assert replacement.confidence == "high"
    assert task.reconciliation_id == replacement.id
    assert persistence.audit_events[0].action == "review_task.reconciliation_corrected"


@pytest.mark.asyncio
async def test_correction_audit_trail_records_before_after_and_metadata() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    corrected_category_id = uuid4()
    proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=tenant_id,
        target_type=ClassificationTargetType.TRANSACTION.value,
        status=ClassificationProposalStatus.PENDING_REVIEW.value,
        version=1,
        confidence="low",
        rationale="Original classifier proposal.",
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        task_type=ReviewTaskType.CLASSIFICATION,
        classification_proposal_id=proposal.id,
    )
    persistence = FakeDecisionPersistence(tasks=[task], proposals=[proposal])

    result = await ReviewTaskDecisionService(persistence).correct_classification(
        tenant_id=tenant_id,
        review_task_id=task.id,
        actor=principal(actor_id),
        corrected_fields={
            "proposed_category_id": corrected_category_id,
            "confidence": "high",
            "rationale": "Corrected during human review.",
        },
        comment="Move to corrected category.",
        reason_code="MANUAL_CATEGORY_FIX",
        correlation_id="corr-audit-001",
    )

    replacement = persistence.proposals[-1]
    audit_event = result.audit_event
    assert audit_event == persistence.audit_events[0]
    assert audit_event.action == "review_task.classification_corrected"
    assert audit_event.tenant_id == tenant_id
    assert audit_event.actor_user_id == actor_id
    assert audit_event.resource_type == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    assert audit_event.resource_id == replacement.id
    assert audit_event.correlation_id == "corr-audit-001"

    assert audit_event.before_state["review_task"]["status"] == (
        ReviewTaskStatus.OPEN.value
    )
    assert audit_event.before_state["review_task"]["resolved_by_user_id"] is None
    assert audit_event.before_state["resource"]["id"] == str(proposal.id)
    assert audit_event.before_state["resource"]["status"] == (
        ClassificationProposalStatus.PENDING_REVIEW.value
    )
    assert audit_event.before_state["resource"]["version"] == 1

    assert audit_event.after_state["review_task"]["status"] == (
        ReviewTaskStatus.RESOLVED.value
    )
    assert audit_event.after_state["review_task"]["resolved_by_user_id"] == str(
        actor_id
    )
    assert audit_event.after_state["superseded_resource"]["id"] == str(proposal.id)
    assert audit_event.after_state["superseded_resource"]["status"] == (
        ClassificationProposalStatus.SUPERSEDED.value
    )
    assert audit_event.after_state["replacement_resource"]["id"] == str(replacement.id)
    assert audit_event.after_state["replacement_resource"]["status"] == (
        ClassificationProposalStatus.PROPOSED.value
    )
    assert audit_event.after_state["replacement_resource"]["version"] == 2

    assert audit_event.metadata_["review_task_id"] == str(task.id)
    assert audit_event.metadata_["comment"] == "Move to corrected category."
    assert audit_event.metadata_["reason_code"] == "MANUAL_CATEGORY_FIX"
    assert audit_event.metadata_["superseded_resource_id"] == str(proposal.id)
    assert audit_event.metadata_["replacement_resource_id"] == str(replacement.id)
    assert audit_event.metadata_["corrected_fields"] == {
        "proposed_category_id": str(corrected_category_id),
        "confidence": "high",
        "rationale": "Corrected during human review.",
    }


@pytest.mark.asyncio
async def test_correction_rejects_unsupported_fields() -> None:
    tenant_id = uuid4()
    invoice = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        status=InvoiceStatus.PENDING_REVIEW.value,
        version=1,
    )
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.INVOICE,
        task_type=ReviewTaskType.EXTRACTION,
        invoice_id=invoice.id,
    )

    with pytest.raises(InvalidReviewCorrectionError):
        await ReviewTaskDecisionService(
            FakeDecisionPersistence(tasks=[task], invoices=[invoice])
        ).correct_extracted_fields(
            tenant_id=tenant_id,
            review_task_id=task.id,
            actor=principal(),
            corrected_fields={"tenant_id": str(uuid4())},
        )


@pytest.mark.asyncio
async def test_decision_service_rejects_missing_review_task() -> None:
    with pytest.raises(ReviewTaskNotFoundError):
        await ReviewTaskDecisionService(FakeDecisionPersistence()).approve_review_task(
            tenant_id=uuid4(),
            review_task_id=uuid4(),
            actor=principal(),
        )


@pytest.mark.asyncio
async def test_decision_service_rejects_already_resolved_task() -> None:
    tenant_id = uuid4()
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        task_type=ReviewTaskType.CLASSIFICATION,
        classification_proposal_id=uuid4(),
        status=ReviewTaskStatus.RESOLVED,
    )

    with pytest.raises(ReviewTaskNotActionableError):
        await ReviewTaskDecisionService(
            FakeDecisionPersistence(tasks=[task])
        ).approve_review_task(
            tenant_id=tenant_id,
            review_task_id=task.id,
            actor=principal(),
        )


@pytest.mark.asyncio
async def test_decision_service_rejects_missing_linked_resource() -> None:
    tenant_id = uuid4()
    task = build_review_task(
        tenant_id=tenant_id,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        task_type=ReviewTaskType.CLASSIFICATION,
        classification_proposal_id=uuid4(),
    )

    with pytest.raises(ReviewResourceNotFoundError):
        await ReviewTaskDecisionService(
            FakeDecisionPersistence(tasks=[task])
        ).approve_review_task(
            tenant_id=tenant_id,
            review_task_id=task.id,
            actor=principal(),
        )


@pytest.mark.asyncio
async def test_decision_service_rejects_tasks_without_supported_resource() -> None:
    tenant_id = uuid4()
    task = ReviewTask(
        id=uuid4(),
        tenant_id=tenant_id,
        task_type=ReviewTaskType.OTHER.value,
        target_type=ReviewTargetType.OTHER.value,
        status=ReviewTaskStatus.OPEN.value,
        priority=ReviewTaskPriority.NORMAL.value,
        title="Unsupported review task",
    )

    with pytest.raises(UnsupportedReviewActionError):
        await ReviewTaskDecisionService(
            FakeDecisionPersistence(tasks=[task])
        ).approve_review_task(
            tenant_id=tenant_id,
            review_task_id=task.id,
            actor=principal(),
        )
