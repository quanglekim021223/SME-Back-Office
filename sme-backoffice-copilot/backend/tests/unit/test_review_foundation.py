from uuid import uuid4

import pytest

from app.models.accounting import (
    ClassificationProposal,
    ClassificationProposalStatus,
    ClassificationTargetType,
    Reconciliation,
    ReconciliationStatus,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.operations import (
    ReviewTargetType,
    ReviewTaskPriority,
    ReviewTaskType,
)
from app.review import (
    REVIEW_TASK_TYPE_DEFINITIONS,
    ImmutableProposalVersioningError,
    ReviewAction,
    ReviewVersionedResource,
    allowed_actions_for_task_type,
    build_classification_supersession_plan,
    build_invoice_extraction_supersession_plan,
    build_reconciliation_supersession_plan,
    get_review_task_type_definition,
    mark_record_superseded,
    task_type_for_target,
)


def test_review_task_type_definitions_cover_all_task_types() -> None:
    defined_task_types = {
        definition.task_type for definition in REVIEW_TASK_TYPE_DEFINITIONS
    }

    assert defined_task_types == set(ReviewTaskType)


def test_classification_review_task_type_allows_decision_and_correction() -> None:
    definition = get_review_task_type_definition(ReviewTaskType.CLASSIFICATION)

    assert definition.target_type == ReviewTargetType.CLASSIFICATION_PROPOSAL
    assert definition.default_priority == ReviewTaskPriority.NORMAL
    assert definition.allowed_actions == (
        ReviewAction.APPROVE_PROPOSAL,
        ReviewAction.REJECT_PROPOSAL,
        ReviewAction.CORRECT_CLASSIFICATION,
    )
    assert (
        task_type_for_target(ReviewTargetType.CLASSIFICATION_PROPOSAL)
        == ReviewTaskType.CLASSIFICATION
    )


def test_extraction_review_task_type_uses_high_priority_invoice_target() -> None:
    definition = get_review_task_type_definition(ReviewTaskType.EXTRACTION)

    assert definition.target_type == ReviewTargetType.INVOICE
    assert definition.default_priority == ReviewTaskPriority.HIGH
    assert ReviewAction.CORRECT_EXTRACTION in allowed_actions_for_task_type(
        ReviewTaskType.EXTRACTION
    )


def test_classification_supersession_plan_creates_new_version_values() -> None:
    proposal_id = uuid4()
    proposal = ClassificationProposal(
        id=proposal_id,
        tenant_id=uuid4(),
        target_type=ClassificationTargetType.TRANSACTION.value,
        status=ClassificationProposalStatus.PENDING_REVIEW.value,
        version=2,
    )

    plan = build_classification_supersession_plan(proposal)

    assert plan.resource == ReviewVersionedResource.CLASSIFICATION_PROPOSAL
    assert plan.target_type == ReviewTargetType.CLASSIFICATION_PROPOSAL
    assert plan.current_record_id == proposal_id
    assert plan.previous_version == 2
    assert plan.new_version == 3
    assert plan.previous_status == ClassificationProposalStatus.PENDING_REVIEW.value
    assert plan.new_record_values() == {
        "supersedes_proposal_id": proposal_id,
        "version": 3,
        "status": ClassificationProposalStatus.PROPOSED.value,
    }

    mark_record_superseded(proposal, plan)

    assert proposal.status == ClassificationProposalStatus.SUPERSEDED.value


def test_reconciliation_supersession_plan_uses_reconciliation_link_field() -> None:
    reconciliation_id = uuid4()
    reconciliation = Reconciliation(
        id=reconciliation_id,
        tenant_id=uuid4(),
        status=ReconciliationStatus.PROPOSED.value,
        version=1,
    )

    plan = build_reconciliation_supersession_plan(reconciliation)

    assert plan.resource == ReviewVersionedResource.RECONCILIATION
    assert plan.new_record_values() == {
        "supersedes_reconciliation_id": reconciliation_id,
        "version": 2,
        "status": ReconciliationStatus.PROPOSED.value,
    }

    mark_record_superseded(reconciliation, plan)

    assert reconciliation.status == ReconciliationStatus.SUPERSEDED.value


def test_invoice_extraction_supersession_plan_uses_invoice_link_field() -> None:
    invoice_id = uuid4()
    invoice = Invoice(
        id=invoice_id,
        tenant_id=uuid4(),
        status=InvoiceStatus.PENDING_REVIEW.value,
        version=4,
    )

    plan = build_invoice_extraction_supersession_plan(invoice)

    assert plan.resource == ReviewVersionedResource.INVOICE_EXTRACTION
    assert plan.new_record_values() == {
        "supersedes_invoice_id": invoice_id,
        "version": 5,
        "status": InvoiceStatus.EXTRACTED.value,
    }

    mark_record_superseded(invoice, plan)

    assert invoice.status == InvoiceStatus.SUPERSEDED.value


def test_supersession_rejects_already_superseded_records() -> None:
    proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=uuid4(),
        target_type=ClassificationTargetType.INVOICE.value,
        status=ClassificationProposalStatus.SUPERSEDED.value,
        version=2,
    )

    with pytest.raises(ImmutableProposalVersioningError):
        build_classification_supersession_plan(proposal)


def test_supersession_plan_must_match_record_id() -> None:
    proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=uuid4(),
        target_type=ClassificationTargetType.INVOICE.value,
        status=ClassificationProposalStatus.PROPOSED.value,
        version=1,
    )
    other_proposal = ClassificationProposal(
        id=uuid4(),
        tenant_id=uuid4(),
        target_type=ClassificationTargetType.INVOICE.value,
        status=ClassificationProposalStatus.PROPOSED.value,
        version=1,
    )
    plan = build_classification_supersession_plan(proposal)

    with pytest.raises(ImmutableProposalVersioningError):
        mark_record_superseded(other_proposal, plan)
