"""Persist workflow outputs into reviewable business proposals."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.models.invoice import (
    Invoice,
    InvoiceDirection,
    InvoiceFieldEvidence,
    InvoiceLineItem,
    InvoiceStatus,
)
from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.validation.deterministic import parse_decimal, parse_iso_date
from app.workflows.contracts import ConfidenceLevel, WorkflowStateStatus
from app.workflows.invoice_extraction import (
    ASSEMBLED_INVOICE_DRAFT_KEY,
    INVOICE_ASSEMBLY_NODE,
    PROVIDER_EXTRACTION_ERRORS_KEY,
    AssembledInvoiceDraft,
    InvoiceLineItemCandidate,
    InvoiceMetadataGroup,
    InvoiceTotalsGroup,
)
from app.workflows.replay import WorkflowReplayResult


class WorkflowOutputPersistence(Protocol):
    """Persistence boundary for materialized workflow outputs."""

    def add_invoice(self, invoice: Invoice) -> Invoice:
        """Stage an extracted invoice proposal."""

    def add_invoice_line_item(self, line_item: InvoiceLineItem) -> InvoiceLineItem:
        """Stage one extracted invoice line item."""

    def add_invoice_field_evidence(
        self,
        field_evidence: InvoiceFieldEvidence,
    ) -> InvoiceFieldEvidence:
        """Stage one extracted field evidence row."""

    def add_review_task(self, review_task: ReviewTask) -> ReviewTask:
        """Stage a human review task."""

    async def mark_document_status(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        status: DocumentStatus,
    ) -> None:
        """Update the source document lifecycle status."""


class SqlAlchemyWorkflowOutputPersistence:
    """SQLAlchemy-backed persistence adapter for workflow output materialization."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_invoice(self, invoice: Invoice) -> Invoice:
        """Stage an extracted invoice proposal."""

        self.session.add(invoice)
        return invoice

    def add_invoice_line_item(self, line_item: InvoiceLineItem) -> InvoiceLineItem:
        """Stage one extracted invoice line item."""

        self.session.add(line_item)
        return line_item

    def add_invoice_field_evidence(
        self,
        field_evidence: InvoiceFieldEvidence,
    ) -> InvoiceFieldEvidence:
        """Stage one extracted field evidence row."""

        self.session.add(field_evidence)
        return field_evidence

    def add_review_task(self, review_task: ReviewTask) -> ReviewTask:
        """Stage a human review task."""

        self.session.add(review_task)
        return review_task

    async def mark_document_status(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        status: DocumentStatus,
    ) -> None:
        """Update the source document lifecycle status when the document exists."""

        document = await self.session.get(Document, document_id)
        if document is None or document.tenant_id != tenant_id:
            return
        document.status = status.value


@dataclass(frozen=True, slots=True)
class MaterializedInvoiceReview:
    """Business records created from one workflow extraction result."""

    invoice: Invoice
    review_task: ReviewTask


class WorkflowOutputPersistenceService:
    """Materialize completed workflow state into reviewable proposal records."""

    def __init__(self, persistence: WorkflowOutputPersistence) -> None:
        self.persistence = persistence

    async def persist_invoice_review_from_workflow_result(
        self,
        result: WorkflowReplayResult,
    ) -> MaterializedInvoiceReview | None:
        """Persist extracted invoice proposal and its human review task.

        The workflow may complete without an invoice draft for unsupported document
        types or failed provider output. In those cases this method returns ``None``
        and leaves the review queue unchanged.
        """

        draft = get_assembled_invoice_draft(result)
        if draft is None:
            if result.state.status == WorkflowStateStatus.FAILED:
                review_task = build_review_task_for_failed_workflow(result)
                self.persistence.add_review_task(review_task)
                await self.persistence.mark_document_status(
                    tenant_id=result.state.tenant_id,
                    document_id=result.state.document_id,
                    status=DocumentStatus.FAILED,
                )
            return None

        invoice = build_invoice_from_draft(result=result, draft=draft)
        self.persistence.add_invoice(invoice)

        for line_item in build_line_items_from_draft(
            tenant_id=result.state.tenant_id,
            invoice_id=invoice.id,
            draft=draft,
        ):
            self.persistence.add_invoice_line_item(line_item)

        for field_evidence in build_field_evidence_from_draft(
            tenant_id=result.state.tenant_id,
            document_id=result.state.document_id,
            invoice_id=invoice.id,
            draft=draft,
        ):
            self.persistence.add_invoice_field_evidence(field_evidence)

        review_task = build_review_task_for_invoice(result=result, invoice=invoice)
        self.persistence.add_review_task(review_task)
        await self.persistence.mark_document_status(
            tenant_id=result.state.tenant_id,
            document_id=result.state.document_id,
            status=DocumentStatus.REVIEW_REQUIRED,
        )
        return MaterializedInvoiceReview(invoice=invoice, review_task=review_task)


def get_assembled_invoice_draft(
    result: WorkflowReplayResult,
) -> AssembledInvoiceDraft | None:
    """Return the assembled invoice draft from workflow scratchpad, if valid."""

    raw_draft = result.state.scratchpad.get(ASSEMBLED_INVOICE_DRAFT_KEY)
    if raw_draft is None:
        return None
    try:
        return AssembledInvoiceDraft.model_validate(raw_draft)
    except ValueError:
        return None


def build_review_task_for_failed_workflow(result: WorkflowReplayResult) -> ReviewTask:
    """Build a document-level review task when workflow processing fails early."""

    return ReviewTask(
        id=uuid4(),
        tenant_id=result.state.tenant_id,
        workflow_run_id=result.workflow_run.id,
        document_id=result.state.document_id,
        task_type=ReviewTaskType.EXTRACTION.value,
        target_type=ReviewTargetType.DOCUMENT.value,
        status=ReviewTaskStatus.OPEN.value,
        priority=ReviewTaskPriority.HIGH.value,
        title="Document processing failed before invoice extraction",
        description=(
            "The document workflow failed before an invoice proposal could be "
            "assembled. Check OCR/provider diagnostics, dependency setup, and "
            "uploaded file readability before retrying."
        ),
        reason_code=result.workflow_run.error_code or "workflow_failed",
        source_agent=result.workflow_run.current_agent,
        evidence_refs=[f"document:{result.state.document_id}"],
        metadata_={
            "source": "workflow_failure",
            "workflow_run_id": str(result.workflow_run.id),
            "workflow_status": result.state.status.value,
            "workflow_stage": result.state.stage.value,
            "error_code": result.workflow_run.error_code,
            "error_message": result.workflow_run.error_message,
        },
    )


def build_invoice_from_draft(
    *,
    result: WorkflowReplayResult,
    draft: AssembledInvoiceDraft,
) -> Invoice:
    """Map an assembled invoice draft to an immutable invoice proposal row."""

    metadata = draft.groups.metadata
    totals = draft.groups.totals
    invoice_id = uuid4()
    confidence = combined_confidence(
        metadata.confidence if metadata is not None else None,
        draft.groups.table.confidence if draft.groups.table is not None else None,
        totals.confidence if totals is not None else None,
    )
    return Invoice(
        id=invoice_id,
        tenant_id=result.state.tenant_id,
        document_id=result.state.document_id,
        status=InvoiceStatus.PENDING_REVIEW.value,
        direction=InvoiceDirection.UNKNOWN.value,
        invoice_number=metadata.invoice_number if metadata is not None else None,
        supplier_name=metadata.supplier_name if metadata is not None else None,
        supplier_tax_id=metadata.supplier_tax_id if metadata is not None else None,
        customer_name=metadata.customer_name if metadata is not None else None,
        customer_tax_id=metadata.customer_tax_id if metadata is not None else None,
        issue_date=parse_iso_date(metadata.issue_date)
        if metadata is not None
        else None,
        due_date=parse_iso_date(metadata.due_date) if metadata is not None else None,
        currency=resolve_invoice_currency(metadata=metadata, totals=totals),
        subtotal_amount=parse_decimal(totals.subtotal_amount)
        if totals is not None
        else None,
        tax_amount=parse_decimal(totals.tax_amount) if totals is not None else None,
        total_amount=parse_decimal(totals.total_amount) if totals is not None else None,
        confidence=confidence.value,
        notes=(
            "Generated by provider-backed workflow and awaiting human review. "
            f"Workflow run: {result.workflow_run.id}."
        ),
    )


def build_line_items_from_draft(
    *,
    tenant_id: UUID,
    invoice_id: UUID,
    draft: AssembledInvoiceDraft,
) -> list[InvoiceLineItem]:
    """Map table group rows to invoice line items."""

    table = draft.groups.table
    if table is None:
        return []
    return [
        build_line_item(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            item=item,
            currency=draft.groups.totals.currency
            if draft.groups.totals is not None
            else None,
        )
        for item in table.line_items
    ]


def build_line_item(
    *,
    tenant_id: UUID,
    invoice_id: UUID,
    item: InvoiceLineItemCandidate,
    currency: str | None,
) -> InvoiceLineItem:
    """Map one extraction line item candidate to an ORM line item."""

    tax_amount = parse_decimal(item.tax_amount)
    total_amount = parse_decimal(item.line_total)
    net_amount = None
    if total_amount is not None and tax_amount is not None:
        net_amount = total_amount - tax_amount

    return InvoiceLineItem(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        line_number=item.line_number,
        description=item.description,
        quantity=parse_decimal(item.quantity),
        unit_price_amount=parse_decimal(item.unit_price),
        net_amount=net_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=currency,
        confidence=item.confidence.value,
    )


def build_field_evidence_from_draft(
    *,
    tenant_id: UUID,
    document_id: UUID,
    invoice_id: UUID,
    draft: AssembledInvoiceDraft,
) -> list[InvoiceFieldEvidence]:
    """Create coarse evidence rows for extracted invoice header and totals."""

    evidence: list[InvoiceFieldEvidence] = []
    metadata = draft.groups.metadata
    totals = draft.groups.totals
    table = draft.groups.table

    if metadata is not None:
        evidence.extend(
            build_group_field_evidence(
                tenant_id=tenant_id,
                document_id=document_id,
                invoice_id=invoice_id,
                group_name="metadata",
                fields={
                    "invoice_number": metadata.invoice_number,
                    "supplier_name": metadata.supplier_name,
                    "supplier_tax_id": metadata.supplier_tax_id,
                    "customer_name": metadata.customer_name,
                    "customer_tax_id": metadata.customer_tax_id,
                    "issue_date": metadata.issue_date,
                    "due_date": metadata.due_date,
                    "currency": metadata.currency,
                },
                confidence=metadata.confidence,
                evidence_refs=metadata.evidence_refs,
            )
        )

    if totals is not None:
        evidence.extend(
            build_group_field_evidence(
                tenant_id=tenant_id,
                document_id=document_id,
                invoice_id=invoice_id,
                group_name="totals",
                fields={
                    "subtotal_amount": totals.subtotal_amount,
                    "tax_amount": totals.tax_amount,
                    "total_amount": totals.total_amount,
                    "currency": totals.currency,
                },
                confidence=totals.confidence,
                evidence_refs=totals.evidence_refs,
            )
        )

    if table is not None and table.evidence_refs:
        evidence.append(
            InvoiceFieldEvidence(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                document_id=document_id,
                field_name="line_items",
                field_path="groups.table.line_items",
                extracted_value=f"{len(table.line_items)} line item(s)",
                normalized_value=str(len(table.line_items)),
                confidence=table.confidence.value,
                source_agent=INVOICE_ASSEMBLY_NODE,
                source_agent_version="0.1.0",
                metadata_={"evidence_refs": table.evidence_refs},
            )
        )

    return evidence


def build_group_field_evidence(
    *,
    tenant_id: UUID,
    document_id: UUID,
    invoice_id: UUID,
    group_name: str,
    fields: dict[str, object | None],
    confidence: ConfidenceLevel,
    evidence_refs: list[str],
) -> list[InvoiceFieldEvidence]:
    """Create evidence rows for non-empty group fields."""

    rows: list[InvoiceFieldEvidence] = []
    for field_name, value in fields.items():
        if value is None:
            continue
        rows.append(
            InvoiceFieldEvidence(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                document_id=document_id,
                field_name=field_name,
                field_path=f"groups.{group_name}.{field_name}",
                extracted_value=str(value),
                normalized_value=str(value),
                confidence=confidence.value,
                source_agent=INVOICE_ASSEMBLY_NODE,
                source_agent_version="0.1.0",
                metadata_={"evidence_refs": evidence_refs},
            )
        )
    return rows


def build_review_task_for_invoice(
    *,
    result: WorkflowReplayResult,
    invoice: Invoice,
) -> ReviewTask:
    """Create a review task for the extracted invoice proposal."""

    raw_draft = cast(
        dict[str, object],
        result.state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY],
    )
    evidence_refs = collect_evidence_refs(raw_draft)
    provider_errors = result.state.scratchpad.get(PROVIDER_EXTRACTION_ERRORS_KEY, [])
    ocr_text_preview = ocr_text_preview_from_state(result)
    invoice_label = invoice.invoice_number or str(invoice.id)
    return ReviewTask(
        id=uuid4(),
        tenant_id=result.state.tenant_id,
        workflow_run_id=result.workflow_run.id,
        document_id=result.state.document_id,
        invoice_id=invoice.id,
        task_type=ReviewTaskType.EXTRACTION.value,
        target_type=ReviewTargetType.INVOICE.value,
        status=ReviewTaskStatus.OPEN.value,
        priority=ReviewTaskPriority.HIGH.value,
        title=f"Review extracted invoice {invoice_label}",
        description=(
            "A provider-backed workflow extracted invoice fields from the uploaded "
            "document. Review the proposal before it affects financial reporting."
        ),
        reason_code="invoice_extraction_requires_human_review",
        source_agent=INVOICE_ASSEMBLY_NODE,
        source_agent_version="0.1.0",
        evidence_refs=evidence_refs,
        metadata_={
            "source": "provider_backed_workflow",
            "workflow_run_id": str(result.workflow_run.id),
            "document_id": str(result.state.document_id),
            "invoice_id": str(invoice.id),
            "proposal_version": invoice.version,
            "assembled_invoice_draft": raw_draft,
            "provider_extraction_errors": provider_errors
            if isinstance(provider_errors, list)
            else [],
            "ocr_text_preview": ocr_text_preview,
        },
    )


def ocr_text_preview_from_state(result: WorkflowReplayResult) -> str | None:
    """Return a bounded OCR text preview for review/debug metadata."""

    ocr_text = result.state.scratchpad.get("ocr_full_text")
    if not isinstance(ocr_text, str) or not ocr_text.strip():
        return None
    return ocr_text[:2000]


def resolve_invoice_currency(
    *,
    metadata: InvoiceMetadataGroup | None,
    totals: InvoiceTotalsGroup | None,
) -> str | None:
    """Prefer totals currency, then metadata currency."""

    if totals is not None and totals.currency is not None:
        return totals.currency
    if metadata is not None:
        return metadata.currency
    return None


def combined_confidence(
    *levels: ConfidenceLevel | None,
) -> ConfidenceLevel:
    """Return the lowest known confidence across extraction groups."""

    known_levels = [level for level in levels if level is not None]
    if not known_levels:
        return ConfidenceLevel.UNKNOWN
    ranks = {
        ConfidenceLevel.UNKNOWN: 0,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.HIGH: 3,
    }
    by_rank = {rank: level for level, rank in ranks.items()}
    return by_rank[min(ranks[level] for level in known_levels)]


def collect_evidence_refs(payload: object) -> list[str]:
    """Collect unique evidence refs from a nested JSON-like payload."""

    refs: list[str] = []
    seen: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "evidence_refs" and isinstance(nested, list):
                    add_refs(cast(Iterable[object], nested))
                else:
                    visit(nested)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    def add_refs(values: Iterable[object]) -> None:
        for value in values:
            if not isinstance(value, str) or value in seen:
                continue
            refs.append(value)
            seen.add(value)

    visit(payload)
    return refs
