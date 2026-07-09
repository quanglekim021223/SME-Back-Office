"""Post-extraction continuation services.

This module keeps downstream accounting work out of review-task decisions. A
human review decision emits an invoice-approved event; these services translate
that event into classification and reconciliation records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from app.classification.hybrid import (
    build_invoice_classification_text,
    classify_with_llm_fallback,
)
from app.classification.rules import (
    CategoryClassificationInput,
    CategoryClassificationResult,
    RuleBasedCategoryClassifier,
)
from app.core.config import LLMProviderType, get_settings
from app.models.accounting import (
    ClassificationProposal,
    ClassificationProposalStatus,
    ClassificationTargetType,
    Reconciliation,
    ReconciliationStatus,
)
from app.models.invoice import Invoice
from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.providers.factory import (
    build_llm_provider_from_settings,
    build_provider_privacy_gate_from_settings,
    build_provider_routing_config_from_settings,
)
from app.providers.llm import LLMProvider
from app.providers.privacy import ProviderPrivacyContext
from app.providers.routing import ProviderRuntime
from app.workflows.contracts import ConfidenceLevel


class PostExtractionPersistence(Protocol):
    """Persistence needed by post-extraction continuation."""

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        """Stage a classification proposal for insertion."""

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        """Stage a reconciliation record for insertion."""

    def add_review_task(self, review_task: ReviewTask) -> ReviewTask:
        """Stage a follow-up review task for insertion."""


@dataclass(frozen=True)
class InvoiceApproved:
    """Event emitted after human review approves an invoice extraction."""

    invoice: Invoice
    source_task: ReviewTask
    source: str = "human_approved_extraction"


class InvoiceApprovedEventPublisher(Protocol):
    """Publishes invoice-approved domain events."""

    async def publish_invoice_approved(self, event: InvoiceApproved) -> None:
        """Publish an invoice-approved event."""


class InProcessInvoiceApprovedPublisher:
    """Synchronous local event publisher used until an outbox/worker exists."""

    def __init__(
        self,
        persistence: PostExtractionPersistence,
        *,
        enable_llm_fallback: bool = False,
    ) -> None:
        provider_runtime: ProviderRuntime | None = None
        llm_provider: LLMProvider | None = None
        privacy_context: ProviderPrivacyContext | None = None
        if enable_llm_fallback:
            settings = get_settings()
            if settings.llm_provider != LLMProviderType.MOCK:
                provider_runtime = ProviderRuntime(
                    build_provider_routing_config_from_settings(settings),
                    privacy_gate=build_provider_privacy_gate_from_settings(settings),
                )
                llm_provider = build_llm_provider_from_settings(settings)
                privacy_context = ProviderPrivacyContext(
                    tenant_allows_cloud=settings.provider_allow_cloud,
                )
        self.service = PostExtractionContinuationService(
            persistence,
            provider_runtime=provider_runtime,
            llm_provider=llm_provider,
            privacy_context=privacy_context,
        )

    async def publish_invoice_approved(self, event: InvoiceApproved) -> None:
        """Handle invoice-approved events in the current transaction."""

        await self.service.handle_invoice_approved(event)


@dataclass(frozen=True)
class PostExtractionContinuationResult:
    """Records created by post-extraction continuation."""

    classification_proposal: ClassificationProposal
    reconciliation: Reconciliation
    classification_review_task: ReviewTask | None


class PostExtractionContinuationService:
    """Runs downstream accounting continuation after extraction review."""

    def __init__(
        self,
        persistence: PostExtractionPersistence,
        *,
        provider_runtime: ProviderRuntime | None = None,
        llm_provider: LLMProvider | None = None,
        privacy_context: ProviderPrivacyContext | None = None,
    ) -> None:
        self.persistence = persistence
        self.provider_runtime = provider_runtime
        self.llm_provider = llm_provider
        self.privacy_context = privacy_context

    async def handle_invoice_approved(
        self,
        event: InvoiceApproved,
    ) -> PostExtractionContinuationResult:
        """Create classification/reconciliation records for an approved invoice."""

        result = await create_post_extraction_continuation(
            event,
            provider_runtime=self.provider_runtime,
            llm_provider=self.llm_provider,
            privacy_context=self.privacy_context,
        )
        self.persistence.add_classification_proposal(result.classification_proposal)
        self.persistence.add_reconciliation(result.reconciliation)
        if result.classification_review_task is not None:
            self.persistence.add_review_task(result.classification_review_task)
        return result


async def create_post_extraction_continuation(
    event: InvoiceApproved,
    *,
    provider_runtime: ProviderRuntime | None = None,
    llm_provider: LLMProvider | None = None,
    privacy_context: ProviderPrivacyContext | None = None,
) -> PostExtractionContinuationResult:
    """Build downstream records from a human-approved invoice."""

    invoice = event.invoice
    source_task = event.source_task
    invoice_label = invoice_review_label(invoice)
    evidence_refs = [f"invoice:{invoice.id}", "review:extraction:approved"]
    classification_result = await classify_human_approved_invoice(
        invoice,
        provider_runtime=provider_runtime,
        llm_provider=llm_provider,
        privacy_context=privacy_context,
        workflow_run_id=source_task.workflow_run_id,
    )
    classification_requires_review = classification_result.confidence in {
        ConfidenceLevel.UNKNOWN,
        ConfidenceLevel.LOW,
    }
    classification = ClassificationProposal(
        id=uuid4(),
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        target_type=ClassificationTargetType.INVOICE.value,
        status=(
            ClassificationProposalStatus.PENDING_REVIEW.value
            if classification_requires_review
            else ClassificationProposalStatus.PROPOSED.value
        ),
        version=1,
        confidence=classification_result.confidence.value,
        source_agent="post_extraction_review_continuation",
        source_agent_version="0.1.0",
        rationale=classification_result.rationale,
        evidence_refs=evidence_refs,
        metadata_={
            "source": event.source,
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "supplier_name": invoice.supplier_name,
            "currency": invoice.currency,
            "total_amount": str(invoice.total_amount)
            if invoice.total_amount is not None
            else None,
            "classifier_name": classification_result.classifier_name,
            "proposed_category_code": classification_result.category_code,
            "proposed_category_type": classification_result.category_type.value,
            "proposed_direction": classification_result.proposed_direction,
            "matched_rule_ids": classification_result.matched_rule_ids,
            "matched_keywords": classification_result.matched_keywords,
            "score": classification_result.score,
        },
    )
    reconciliation = Reconciliation(
        id=uuid4(),
        tenant_id=invoice.tenant_id,
        status=ReconciliationStatus.PROPOSED.value,
        version=1,
        currency=invoice.currency,
        invoice_total_amount=invoice.total_amount,
        transaction_total_amount=None,
        difference_amount=invoice.total_amount,
        confidence="unknown",
        source_agent="post_extraction_review_continuation",
        source_agent_version="0.1.0",
        rationale="Human-approved extraction needs bank transaction matching.",
        evidence_refs=[f"invoice:{invoice.id}", f"classification:{classification.id}"],
        metadata_={
            "source": event.source,
            "invoice_id": str(invoice.id),
            "classification_proposal_id": str(classification.id),
            "requires_review": False,
            "review_reason": "awaiting_transaction_match",
            "candidate_count": 0,
        },
    )
    classification_task = (
        ReviewTask(
            id=uuid4(),
            tenant_id=invoice.tenant_id,
            workflow_run_id=source_task.workflow_run_id,
            document_id=invoice.document_id,
            invoice_id=invoice.id,
            classification_proposal_id=classification.id,
            task_type=ReviewTaskType.CLASSIFICATION.value,
            target_type=ReviewTargetType.CLASSIFICATION_PROPOSAL.value,
            status=ReviewTaskStatus.OPEN.value,
            priority=ReviewTaskPriority.NORMAL.value,
            title=f"Review classification for invoice {invoice_label}",
            description=(
                "Extraction was human-approved. Review the accounting "
                "classification before it affects reporting."
            ),
            reason_code="classification_after_extraction_review",
            source_agent="post_extraction_review_continuation",
            source_agent_version="0.1.0",
            evidence_refs=classification.evidence_refs,
            metadata_={
                "source": event.source,
                "invoice_id": str(invoice.id),
                "classification_proposal_id": str(classification.id),
                "proposed_category_code": classification_result.category_code,
                "proposed_category_type": classification_result.category_type.value,
                "proposed_direction": classification_result.proposed_direction,
                "confidence": classification_result.confidence.value,
                "rationale": classification_result.rationale,
                "matched_rule_ids": classification_result.matched_rule_ids,
                "matched_keywords": classification_result.matched_keywords,
                "score": classification_result.score,
            },
        )
        if classification_requires_review
        else None
    )
    return PostExtractionContinuationResult(
        classification_proposal=classification,
        reconciliation=reconciliation,
        classification_review_task=classification_task,
    )


async def classify_human_approved_invoice(
    invoice: Invoice,
    *,
    provider_runtime: ProviderRuntime | None = None,
    llm_provider: LLMProvider | None = None,
    privacy_context: ProviderPrivacyContext | None = None,
    workflow_run_id: object | None = None,
) -> CategoryClassificationResult:
    """Run deterministic classification on a human-approved invoice row."""

    line_items = getattr(invoice, "line_items", []) or []
    classification_input = CategoryClassificationInput(
        target_type=ClassificationTargetType.INVOICE,
        text=build_invoice_classification_text(
            invoice_number=invoice.invoice_number,
            supplier_name=invoice.supplier_name,
            customer_name=invoice.customer_name,
            line_item_descriptions=[item.description for item in line_items],
        ),
        amount=invoice.total_amount,
        currency=invoice.currency,
        counterparty_name=invoice.supplier_name or invoice.customer_name,
        reference=invoice.invoice_number,
        metadata={
            "source": "human_approved_invoice",
            "invoice_direction": invoice.direction,
        },
    )
    if provider_runtime is None or llm_provider is None:
        return RuleBasedCategoryClassifier().classify(classification_input)
    return await classify_with_llm_fallback(
        classification_input,
        tenant_id=invoice.tenant_id,
        document_id=invoice.document_id,
        workflow_run_id=workflow_run_id,  # type: ignore[arg-type]
        provider_runtime=provider_runtime,
        llm_provider=llm_provider,
        privacy_context=privacy_context,
    )


def invoice_review_label(invoice: Invoice) -> str:
    """Return a compact invoice label for review task titles."""

    if invoice.invoice_number and invoice.invoice_number.strip():
        return invoice.invoice_number.strip()
    return str(invoice.id)[:8]
