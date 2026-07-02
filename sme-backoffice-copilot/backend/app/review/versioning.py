"""Immutable supersession helpers for review corrections."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.accounting import (
    ClassificationProposal,
    ClassificationProposalStatus,
    Reconciliation,
    ReconciliationStatus,
)
from app.models.invoice import Invoice, InvoiceStatus
from app.models.operations import ReviewTargetType
from app.review.contracts import ReviewAction


class ReviewVersionedResource(StrEnum):
    """Versioned resource families corrected through human review."""

    INVOICE_EXTRACTION = "invoice_extraction"
    CLASSIFICATION_PROPOSAL = "classification_proposal"
    RECONCILIATION = "reconciliation"


class ImmutableProposalVersioningError(ValueError):
    """Raised when a review correction cannot create a new immutable version."""


class SupersedableRecord(Protocol):
    """Minimal record shape required to apply a superseded status."""

    id: UUID
    status: str


class SupersessionPlan(BaseModel):
    """Plan for creating a replacement record while preserving the old one."""

    model_config = ConfigDict(extra="forbid")

    resource: ReviewVersionedResource
    target_type: ReviewTargetType
    current_record_id: UUID
    supersedes_field_name: str = Field(min_length=1)
    previous_status: str = Field(min_length=1)
    superseded_status: str = Field(min_length=1)
    previous_version: int = Field(ge=1)
    new_version: int = Field(ge=2)
    new_record_status: str = Field(min_length=1)
    review_action: ReviewAction
    reason: str = Field(min_length=1)

    def new_record_values(self) -> dict[str, object]:
        """Return required values for the replacement record."""

        return {
            self.supersedes_field_name: self.current_record_id,
            "version": self.new_version,
            "status": self.new_record_status,
        }

    def old_record_status_update(self) -> dict[str, object]:
        """Return the only status update expected on the old record."""

        return {"status": self.superseded_status}


def build_classification_supersession_plan(
    current: ClassificationProposal,
    *,
    new_status: ClassificationProposalStatus = ClassificationProposalStatus.PROPOSED,
    review_action: ReviewAction = ReviewAction.CORRECT_CLASSIFICATION,
    reason: str = "Human correction creates a new classification proposal version.",
) -> SupersessionPlan:
    """Plan a replacement classification proposal without overwriting the old one."""

    ensure_not_already_superseded(
        status=current.status,
        superseded_status=ClassificationProposalStatus.SUPERSEDED.value,
    )
    return SupersessionPlan(
        resource=ReviewVersionedResource.CLASSIFICATION_PROPOSAL,
        target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL,
        current_record_id=current.id,
        supersedes_field_name="supersedes_proposal_id",
        previous_status=current.status,
        superseded_status=ClassificationProposalStatus.SUPERSEDED.value,
        previous_version=current.version,
        new_version=current.version + 1,
        new_record_status=new_status.value,
        review_action=review_action,
        reason=reason,
    )


def build_reconciliation_supersession_plan(
    current: Reconciliation,
    *,
    new_status: ReconciliationStatus = ReconciliationStatus.PROPOSED,
    review_action: ReviewAction = ReviewAction.CORRECT_RECONCILIATION,
    reason: str = "Human correction creates a new reconciliation version.",
) -> SupersessionPlan:
    """Plan a replacement reconciliation without overwriting the old one."""

    ensure_not_already_superseded(
        status=current.status,
        superseded_status=ReconciliationStatus.SUPERSEDED.value,
    )
    return SupersessionPlan(
        resource=ReviewVersionedResource.RECONCILIATION,
        target_type=ReviewTargetType.RECONCILIATION,
        current_record_id=current.id,
        supersedes_field_name="supersedes_reconciliation_id",
        previous_status=current.status,
        superseded_status=ReconciliationStatus.SUPERSEDED.value,
        previous_version=current.version,
        new_version=current.version + 1,
        new_record_status=new_status.value,
        review_action=review_action,
        reason=reason,
    )


def build_invoice_extraction_supersession_plan(
    current: Invoice,
    *,
    new_status: InvoiceStatus = InvoiceStatus.EXTRACTED,
    review_action: ReviewAction = ReviewAction.CORRECT_EXTRACTION,
    reason: str = "Human correction creates a new invoice extraction version.",
) -> SupersessionPlan:
    """Plan a replacement invoice extraction without overwriting the old one."""

    ensure_not_already_superseded(
        status=current.status,
        superseded_status=InvoiceStatus.SUPERSEDED.value,
    )
    return SupersessionPlan(
        resource=ReviewVersionedResource.INVOICE_EXTRACTION,
        target_type=ReviewTargetType.INVOICE,
        current_record_id=current.id,
        supersedes_field_name="supersedes_invoice_id",
        previous_status=current.status,
        superseded_status=InvoiceStatus.SUPERSEDED.value,
        previous_version=current.version,
        new_version=current.version + 1,
        new_record_status=new_status.value,
        review_action=review_action,
        reason=reason,
    )


def mark_record_superseded(
    record: SupersedableRecord,
    plan: SupersessionPlan,
) -> None:
    """Apply the superseded status to an old record without mutating its payload."""

    record_id = getattr(record, "id", None)
    if record_id != plan.current_record_id:
        raise ImmutableProposalVersioningError(
            "Supersession plan does not match the record being superseded."
        )
    record.status = plan.superseded_status


def ensure_not_already_superseded(*, status: str, superseded_status: str) -> None:
    """Reject attempts to supersede a record that is already superseded."""

    if status == superseded_status:
        raise ImmutableProposalVersioningError(
            "Cannot supersede a record that is already superseded."
        )
