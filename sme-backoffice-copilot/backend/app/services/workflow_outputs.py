"""Persist workflow outputs into reviewable business proposals."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import (
    Category,
    ClassificationProposal,
    Reconciliation,
    ReconciliationAllocation,
)
from app.models.banking import Transaction
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
from app.observability.tracing import record_trace_event
from app.validation.deterministic import parse_decimal, parse_iso_date
from app.workflows.contracts import ConfidenceLevel, WorkflowStateStatus
from app.workflows.downstream_agents import (
    CLASSIFICATION_PROPOSAL_KEY,
    RECONCILIATION_RESULT_KEY,
)
from app.workflows.invoice_extraction import (
    ASSEMBLED_INVOICE_DRAFT_KEY,
    EXTRACTION_ROUTING_DECISIONS_KEY,
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

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        """Stage a classification proposal."""

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        """Stage a reconciliation match."""

    def add_reconciliation_allocation(
        self,
        allocation: ReconciliationAllocation,
    ) -> ReconciliationAllocation:
        """Stage a reconciliation allocation."""

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

    def add_classification_proposal(
        self,
        proposal: ClassificationProposal,
    ) -> ClassificationProposal:
        """Stage a classification proposal."""

        self.session.add(proposal)
        return proposal

    def add_reconciliation(self, reconciliation: Reconciliation) -> Reconciliation:
        """Stage a reconciliation match."""

        self.session.add(reconciliation)
        return reconciliation

    def add_reconciliation_allocation(
        self,
        allocation: ReconciliationAllocation,
    ) -> ReconciliationAllocation:
        """Stage a reconciliation allocation."""

        self.session.add(allocation)
        return allocation

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

    def __init__(
        self,
        persistence: WorkflowOutputPersistence,
        *,
        trace_provider: object | None = None,
    ) -> None:
        self.persistence = persistence
        self.trace_provider = trace_provider

    async def persist_invoice_review_from_workflow_result(
        self,
        result: WorkflowReplayResult,
    ) -> MaterializedInvoiceReview | None:
        """Persist extracted invoice proposal and its human review task.

        The workflow may complete without an invoice draft for unsupported document
        types or failed provider output. Provider failures create a document-level
        review task so the upload never disappears from human review.
        """

        draft = get_assembled_invoice_draft(result)
        if draft is None:
            if result.state.status in {
                WorkflowStateStatus.FAILED,
                WorkflowStateStatus.REVIEW_REQUIRED,
            }:
                review_task = build_review_task_for_failed_workflow(result)
                self.persistence.add_review_task(review_task)
                self._trace_review_task_created(
                    review_task=review_task,
                    source="workflow_failure",
                    result=result,
                )
                await self.persistence.mark_document_status(
                    tenant_id=result.state.tenant_id,
                    document_id=result.state.document_id,
                    status=DocumentStatus.REVIEW_REQUIRED,
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
            layout_blocks=ocr_layout_blocks_from_state(result),
        ):
            self.persistence.add_invoice_field_evidence(field_evidence)

        # Build and persist ClassificationProposal if present in workflow
        classification_proposal = await build_classification_proposal(
            persistence=self.persistence,
            tenant_id=result.state.tenant_id,
            invoice_id=invoice.id,
            result=result,
        )
        if classification_proposal is not None:
            self.persistence.add_classification_proposal(classification_proposal)

        # Build and persist Reconciliation and Allocations if present in workflow
        reconciliation, allocations = await build_reconciliation_and_allocations(
            persistence=self.persistence,
            tenant_id=result.state.tenant_id,
            invoice_id=invoice.id,
            invoice_amount=invoice.total_amount,
            invoice_currency=invoice.currency,
            result=result,
        )
        if reconciliation is not None:
            self.persistence.add_reconciliation(reconciliation)
            for allocation in allocations:
                self.persistence.add_reconciliation_allocation(allocation)

        review_task = build_review_task_for_invoice(
            result=result,
            invoice=invoice,
            classification_proposal_id=(
                classification_proposal.id
                if classification_proposal is not None
                else None
            ),
            reconciliation_id=reconciliation.id if reconciliation is not None else None,
        )
        self.persistence.add_review_task(review_task)
        self._trace_review_task_created(
            review_task=review_task,
            source="invoice_proposal",
            result=result,
        )
        await self.persistence.mark_document_status(
            tenant_id=result.state.tenant_id,
            document_id=result.state.document_id,
            status=DocumentStatus.REVIEW_REQUIRED,
        )
        return MaterializedInvoiceReview(invoice=invoice, review_task=review_task)

    def _trace_review_task_created(
        self,
        *,
        review_task: ReviewTask,
        source: str,
        result: WorkflowReplayResult,
    ) -> None:
        """Trace review-task creation without exposing extracted invoice content."""

        record_trace_event(
            self.trace_provider,
            "review_task.created",
            {
                "source": source,
                "review_task_id": str(review_task.id),
                "task_type": review_task.task_type,
                "target_type": review_task.target_type,
                "status": review_task.status,
                "priority": review_task.priority,
                "reason_code": review_task.reason_code,
                "source_agent": review_task.source_agent,
                "has_invoice_id": review_task.invoice_id is not None,
                "evidence_ref_count": len(review_task.evidence_refs or []),
                "workflow_run_id": str(result.workflow_run.id),
                "workflow_status": result.state.status.value,
            },
            correlation_id=result.workflow_run.correlation_id,
        )


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
    """Map table group rows to invoice line items, de-duplicating line numbers."""

    table = draft.groups.table
    if table is None:
        return []

    line_items = []
    seen_line_numbers = set()
    next_auto_line_number = 1

    for item in table.line_items:
        line_num = item.line_number
        if line_num is None or line_num <= 0 or line_num in seen_line_numbers:
            while next_auto_line_number in seen_line_numbers:
                next_auto_line_number += 1
            line_num = next_auto_line_number
            next_auto_line_number += 1

        seen_line_numbers.add(line_num)
        item_copy = item.model_copy(update={"line_number": line_num})

        line_items.append(
            build_line_item(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                item=item_copy,
                currency=draft.groups.totals.currency
                if draft.groups.totals is not None
                else None,
            )
        )
    return line_items


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
    layout_blocks: list[dict[str, object]] | None = None,
) -> list[InvoiceFieldEvidence]:
    """Create field-level evidence rows grounded to concrete OCR blocks."""

    evidence: list[InvoiceFieldEvidence] = []
    blocks = layout_blocks or []
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
                layout_blocks=blocks,
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
                layout_blocks=blocks,
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
    layout_blocks: list[dict[str, object]],
) -> list[InvoiceFieldEvidence]:
    """Create evidence rows for non-empty group fields."""

    rows: list[InvoiceFieldEvidence] = []
    for field_name, value in fields.items():
        if value is None:
            continue
        matched_blocks = match_ocr_blocks(
            value=value,
            field_name=field_name,
            layout_blocks=layout_blocks,
        )
        matched_refs = [
            block_id
            for block in matched_blocks
            if (block_id := block.get("id")) and isinstance(block_id, str)
        ]
        primary_block = matched_blocks[0] if matched_blocks else None
        bounding_box = (
            primary_block.get("bounding_box") if primary_block is not None else None
        )
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
                page_number=(
                    primary_block.get("page_number")
                    if primary_block is not None
                    and isinstance(primary_block.get("page_number"), int)
                    else None
                ),
                bounding_box=(
                    {"polygon": bounding_box}
                    if isinstance(bounding_box, list)
                    else None
                ),
                source_agent=INVOICE_ASSEMBLY_NODE,
                source_agent_version="0.1.0",
                metadata_={
                    "evidence_refs": matched_refs,
                    "group_evidence_refs": evidence_refs,
                    "grounding_method": (
                        "ocr_block_match" if matched_refs else "unresolved"
                    ),
                },
            )
        )
    return rows


def build_review_field_grounding(
    *,
    draft: AssembledInvoiceDraft,
    layout_blocks: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Map review-card fields to stable OCR block IDs."""

    metadata = draft.groups.metadata
    totals = draft.groups.totals
    candidates: tuple[tuple[str, str, object | None], ...] = (
        (
            "invoice_number",
            "groups.metadata.invoice_number",
            metadata.invoice_number if metadata else None,
        ),
        (
            "supplier",
            "groups.metadata.supplier_name",
            metadata.supplier_name if metadata else None,
        ),
        (
            "supplier_tax_id",
            "groups.metadata.supplier_tax_id",
            metadata.supplier_tax_id if metadata else None,
        ),
        (
            "customer",
            "groups.metadata.customer_name",
            metadata.customer_name if metadata else None,
        ),
        (
            "customer_tax_id",
            "groups.metadata.customer_tax_id",
            metadata.customer_tax_id if metadata else None,
        ),
        (
            "issue_date",
            "groups.metadata.issue_date",
            metadata.issue_date if metadata else None,
        ),
        (
            "due_date",
            "groups.metadata.due_date",
            metadata.due_date if metadata else None,
        ),
        (
            "subtotal",
            "groups.totals.subtotal_amount",
            totals.subtotal_amount if totals else None,
        ),
        (
            "tax",
            "groups.totals.tax_amount",
            totals.tax_amount if totals else None,
        ),
        (
            "total",
            "groups.totals.total_amount",
            totals.total_amount if totals else None,
        ),
    )
    grounding: dict[str, dict[str, object]] = {}
    for field_kind, field_path, value in candidates:
        if value is None:
            continue
        blocks = match_ocr_blocks(
            value=value,
            field_name=field_kind,
            layout_blocks=layout_blocks,
        )
        grounding[field_kind] = {
            "field_path": field_path,
            "block_ids": [
                block["id"] for block in blocks if isinstance(block.get("id"), str)
            ],
        }
    return grounding


def match_ocr_blocks(
    *,
    value: object,
    field_name: str,
    layout_blocks: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return the best OCR block for a field without weak token matching."""

    value_text = str(value).strip()
    normalized_value = normalize_evidence_text(value_text)
    if not normalized_value:
        return []

    date_keys = evidence_date_keys(value_text)
    amount = (
        evidence_decimal(value_text)
        if "amount" in field_name or field_name in {"subtotal", "tax", "total"}
        else None
    )
    anchors = evidence_field_anchors(field_name)
    anchor_indexes = [
        index
        for index, block in enumerate(layout_blocks)
        if any(
            normalize_evidence_text(str(block.get("text") or "")) == anchor
            or normalize_evidence_text(str(block.get("text") or "")).startswith(
                f"{anchor} "
            )
            for anchor in anchors
        )
    ]
    scored: list[tuple[int, int, dict[str, object]]] = []
    for index, block in enumerate(layout_blocks):
        block_text = block.get("text")
        if not isinstance(block_text, str):
            continue
        normalized_block = normalize_evidence_text(block_text)
        score = 0
        if normalized_block == normalized_value:
            score = 100
        elif date_keys and date_keys.intersection(evidence_date_keys(block_text)):
            score = 95
        elif amount is not None and amount in evidence_decimals(block_text):
            score = 85
        elif len(normalized_value) >= 3 and (
            normalized_value in normalized_block
            or (len(normalized_block) >= 4 and normalized_block in normalized_value)
        ):
            score = 75
        if score == 0:
            continue
        if any(anchor in normalized_block for anchor in anchors):
            score += 25
        preceding = [anchor for anchor in anchor_indexes if anchor < index]
        if preceding:
            distance = index - max(preceding)
            score += max(0, 20 - distance)
        scored.append((score, -index, block))

    if not scored:
        return []
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [scored[0][2]]


def normalize_evidence_text(value: str) -> str:
    """Normalize OCR and extracted values for conservative text matching."""

    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def evidence_date_keys(value: str) -> set[tuple[int, int, int]]:
    """Return plausible date keys while supporting ISO and common OCR formats."""

    stripped = value.strip()
    try:
        parsed = date.fromisoformat(stripped[:10])
        return {(parsed.year, parsed.month, parsed.day)}
    except ValueError:
        pass

    portuguese_months = {
        "jan": 1,
        "fev": 2,
        "mar": 3,
        "abr": 4,
        "mai": 5,
        "jun": 6,
        "jul": 7,
        "ago": 8,
        "set": 9,
        "out": 10,
        "nov": 11,
        "dez": 12,
    }
    localized_match = re.search(
        r"\b(\d{1,2})\s+(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)"
        r"\s+(\d{4})\b",
        stripped.casefold(),
    )
    if localized_match is not None:
        day, month_name, year = localized_match.groups()
        localized_key = (int(year), portuguese_months[month_name], int(day))
        return {localized_key} if is_valid_date_key(localized_key) else set()

    match = re.search(r"(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})", stripped)
    if match is None:
        return set()
    first, second, third = (int(part) for part in match.groups())
    if first >= 1000:
        return {(first, second, third)}
    if third < 1000:
        return set()

    candidates: set[tuple[int, int, int]] = set()
    if first <= 12:
        candidates.add((third, first, second))
    if second <= 12:
        candidates.add((third, second, first))
    return {candidate for candidate in candidates if is_valid_date_key(candidate)}


def is_valid_date_key(value: tuple[int, int, int]) -> bool:
    try:
        date(*value)
    except ValueError:
        return False
    return True


def evidence_decimal(value: str) -> Decimal | None:
    values = evidence_decimals(value)
    return values[0] if len(values) == 1 else None


def evidence_decimals(value: str) -> list[Decimal]:
    """Extract locale-tolerant decimal candidates from one OCR block."""

    decimals: list[Decimal] = []
    for token in re.findall(r"[-+]?\d[\d,.]*", value):
        normalized = token.replace(",", "")
        try:
            decimals.append(Decimal(normalized))
        except ArithmeticError:
            continue
    return decimals


def evidence_field_anchors(field_name: str) -> set[str]:
    anchors = {
        "invoice_number": {"invoice", "invoice no", "invoice number"},
        "supplier": {"supplier", "vendor", "seller"},
        "supplier_name": {"supplier", "vendor", "seller"},
        "supplier_tax_id": {"vendor tax id", "supplier tax id", "nif"},
        "customer": {"bill to", "customer", "client"},
        "customer_name": {"bill to", "customer", "client"},
        "customer_tax_id": {"customer tax id", "contribuinte", "nif"},
        "issue_date": {"invoice date", "issue date", "date", "data"},
        "due_date": {"due date", "payment due"},
        "total": {"total", "amount due", "balance due"},
        "total_amount": {"total", "amount due", "balance due"},
        "subtotal": {"subtotal", "sub total"},
        "subtotal_amount": {"subtotal", "sub total"},
        "tax": {"tax", "vat", "iva", "valor iva", "tx iva"},
        "tax_amount": {"tax", "vat", "iva", "valor iva", "tx iva"},
    }
    return anchors.get(field_name, set())


def build_review_task_for_invoice(
    *,
    result: WorkflowReplayResult,
    invoice: Invoice,
    classification_proposal_id: UUID | None = None,
    reconciliation_id: UUID | None = None,
) -> ReviewTask:
    """Create a review task for the extracted invoice proposal."""

    raw_draft = cast(
        dict[str, object],
        result.state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY],
    )
    evidence_refs = collect_evidence_refs(raw_draft)
    provider_errors = result.state.scratchpad.get(PROVIDER_EXTRACTION_ERRORS_KEY, [])
    extraction_routing = result.state.scratchpad.get(
        EXTRACTION_ROUTING_DECISIONS_KEY,
        {},
    )
    ocr_text_preview = ocr_text_preview_from_state(result)
    ocr_layout_diagnostics = ocr_layout_diagnostics_from_state(result)
    ocr_layout_blocks = ocr_layout_blocks_from_state(result)
    field_grounding = build_review_field_grounding(
        draft=AssembledInvoiceDraft.model_validate(raw_draft),
        layout_blocks=ocr_layout_blocks,
    )
    invoice_label = invoice.invoice_number or str(invoice.id)
    return ReviewTask(
        id=uuid4(),
        tenant_id=result.state.tenant_id,
        workflow_run_id=result.workflow_run.id,
        document_id=result.state.document_id,
        invoice_id=invoice.id,
        classification_proposal_id=classification_proposal_id,
        reconciliation_id=reconciliation_id,
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
            "extraction_routing": extraction_routing
            if isinstance(extraction_routing, dict)
            else {},
            "ocr_text_preview": ocr_text_preview,
            "ocr_layout_diagnostics": ocr_layout_diagnostics,
            "ocr_layout_blocks": ocr_layout_blocks,
            "field_evidence_grounding": field_grounding,
        },
    )


async def build_classification_proposal(
    *,
    persistence: WorkflowOutputPersistence,
    tenant_id: UUID,
    invoice_id: UUID,
    result: WorkflowReplayResult,
) -> ClassificationProposal | None:
    """Build a classification proposal record from workflow output if available."""

    raw_payload = result.state.scratchpad.get(CLASSIFICATION_PROPOSAL_KEY)
    if raw_payload is None:
        return None

    try:
        from app.workflows.downstream_agents import ClassificationDraft

        draft = ClassificationDraft.model_validate(raw_payload)
    except Exception:
        return None

    category_id = None
    if draft.proposed_category_code and hasattr(persistence, "session"):
        session = persistence.session
        try:
            stmt = select(Category).where(
                Category.tenant_id == tenant_id,
                Category.slug == draft.proposed_category_code,
            )
            res = await session.execute(stmt)
            cat = res.scalar_one_or_none()
            if cat is not None:
                category_id = cat.id
        except Exception:
            pass

    return ClassificationProposal(
        id=uuid4(),
        tenant_id=tenant_id,
        proposed_category_id=category_id,
        invoice_id=invoice_id,
        target_type="invoice",
        status="proposed",
        version=1,
        confidence=draft.confidence.value,
        source_agent="classification_agent",
        source_agent_version="0.1.0",
        rationale=draft.rationale,
        evidence_refs=draft.evidence_refs,
        metadata_={
            "proposed_category_code": draft.proposed_category_code,
            "proposed_direction": draft.proposed_direction,
        },
    )


async def build_reconciliation_and_allocations(
    *,
    persistence: WorkflowOutputPersistence,
    tenant_id: UUID,
    invoice_id: UUID,
    invoice_amount: Decimal | None,
    invoice_currency: str | None,
    result: WorkflowReplayResult,
) -> tuple[Reconciliation | None, list[ReconciliationAllocation]]:
    """Build reconciliation and allocation records from workflow output if available."""

    raw_payload = result.state.scratchpad.get(RECONCILIATION_RESULT_KEY)
    if raw_payload is None:
        return None, []

    try:
        from app.workflows.downstream_agents import ReconciliationDraft

        draft = ReconciliationDraft.model_validate(raw_payload)
    except Exception:
        return None, []

    recon_id = uuid4()
    allocations: list[ReconciliationAllocation] = []
    total_tx_amount = Decimal("0.00")

    # Map transaction refs to UUIDs
    matched_ids = []
    for tx_id_str in draft.matched_transaction_refs:
        try:
            tx_uuid = UUID(tx_id_str)
            matched_ids.append(tx_uuid)
        except ValueError:
            continue

    db_transactions: list[Transaction] = []
    if matched_ids and hasattr(persistence, "session"):
        session = persistence.session
        try:
            stmt = select(Transaction).where(
                Transaction.tenant_id == tenant_id,
                Transaction.id.in_(matched_ids),
            )
            res = await session.execute(stmt)
            db_transactions = list(res.scalars().all())

        except Exception:
            pass

    for tx in db_transactions:
        allocated = abs(tx.amount)
        total_tx_amount += allocated
        allocations.append(
            ReconciliationAllocation(
                id=uuid4(),
                tenant_id=tenant_id,
                reconciliation_id=recon_id,
                invoice_id=invoice_id,
                transaction_id=tx.id,
                status="proposed",
                allocated_amount=allocated,
                currency=tx.currency,
                allocation_method="deterministic",
                confidence=draft.confidence.value,
                notes=(
                    "Auto-allocated by deterministic reconciliation matching. "
                    f"Score/confidence: {draft.confidence.value}"
                ),
            )
        )

    # If no db transactions are resolved (e.g. offline testing/replay),
    # construct default allocations to match the draft references
    if not allocations and matched_ids and not hasattr(persistence, "session"):
        for tx_id in matched_ids:
            allocated = abs(invoice_amount or Decimal("0.00"))
            total_tx_amount += allocated
            allocations.append(
                ReconciliationAllocation(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    reconciliation_id=recon_id,
                    invoice_id=invoice_id,
                    transaction_id=tx_id,
                    status="proposed",
                    allocated_amount=allocated,
                    currency=invoice_currency or "USD",
                    allocation_method="deterministic",
                    confidence=draft.confidence.value,
                    notes=(
                        "Synthetic allocation for testing/offline replay. "
                        f"Score/confidence: {draft.confidence.value}"
                    ),
                )
            )

    diff_amount = None
    if invoice_amount is not None:
        diff_amount = abs(invoice_amount) - total_tx_amount

    reconciliation = Reconciliation(
        id=recon_id,
        tenant_id=tenant_id,
        supersedes_reconciliation_id=None,
        status="proposed",
        match_type="one_to_one" if len(allocations) <= 1 else "one_to_many",
        version=1,
        currency=invoice_currency or (allocations[0].currency if allocations else None),
        invoice_total_amount=invoice_amount,
        transaction_total_amount=total_tx_amount,
        difference_amount=diff_amount,
        confidence=draft.confidence.value,
        source_agent="reconciliation_agent",
        source_agent_version="0.1.0",
        rationale=(
            "Deterministic matching engine found "
            f"{len(allocations)} candidate(s) above threshold."
        ),
        evidence_refs=[CLASSIFICATION_PROPOSAL_KEY],
        metadata_={
            "requires_review": draft.requires_review,
            "review_reason": draft.review_reason,
            "candidate_count": draft.candidate_count,
            "candidate_score": getattr(draft, "candidate_score", None),
        },
    )

    return reconciliation, allocations


def ocr_text_preview_from_state(result: WorkflowReplayResult) -> str | None:
    """Return a bounded OCR text preview for review/debug metadata."""

    ocr_text = result.state.scratchpad.get("ocr_full_text")
    if not isinstance(ocr_text, str) or not ocr_text.strip():
        return None
    return ocr_text[:2000]


def ocr_layout_diagnostics_from_state(
    result: WorkflowReplayResult,
) -> dict[str, object] | None:
    """Return OCR layout diagnostics from workflow state when available."""

    diagnostics = result.state.scratchpad.get("ocr_layout_diagnostics")
    return diagnostics if isinstance(diagnostics, dict) else None


def ocr_layout_blocks_from_state(
    result: WorkflowReplayResult,
) -> list[dict[str, object]]:
    """Return bounded OCR regions for the human evidence viewer."""

    blocks = result.state.scratchpad.get("ocr_layout_blocks")
    if not isinstance(blocks, list):
        return []

    return [dict(block) for block in blocks[:250] if isinstance(block, dict)]


def resolve_invoice_currency(
    *,
    metadata: InvoiceMetadataGroup | None,
    totals: InvoiceTotalsGroup | None,
) -> str | None:
    """Prefer totals currency, then metadata currency."""

    if totals is not None and totals.currency is not None:
        return normalize_currency_code(totals.currency)
    if metadata is not None:
        return normalize_currency_code(metadata.currency)
    return None


def normalize_currency_code(value: str | None) -> str | None:
    """Return a safe ISO-like three-letter currency code for persistence."""

    if value is None:
        return None
    normalized = value.strip().upper()
    aliases = {
        "€": "EUR",
        "EURO": "EUR",
        "EUROS": "EUR",
        "$": "USD",
        "DOLLAR": "USD",
        "DOLLARS": "USD",
        "£": "GBP",
        "POUND": "GBP",
        "POUNDS": "GBP",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if re.fullmatch(r"[A-Z]{3}", normalized) else None


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
