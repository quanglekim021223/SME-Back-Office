"""Deterministic invoice-to-transaction reconciliation matching."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.fixtures.loader import StatementTransactionFixture
from app.models.banking import TransactionDirection
from app.validation import parse_decimal, parse_iso_date
from app.workflows.contracts import ConfidenceLevel
from app.workflows.invoice_extraction import InvoiceExtractionGroups

DEFAULT_MATCH_THRESHOLD = 70
DEFAULT_AMOUNT_TOLERANCE = Decimal("0.01")


class ReconciliationInvoiceInput(BaseModel):
    """Normalized invoice input used by deterministic reconciliation."""

    model_config = ConfigDict(extra="forbid")

    invoice_number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    counterparty_names: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ReconciliationTransactionInput(BaseModel):
    """Normalized transaction input used by deterministic reconciliation."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    posted_at: date | None = None
    value_at: date | None = None
    amount: Decimal
    currency: str | None = None
    direction: TransactionDirection = TransactionDirection.UNKNOWN
    reference: str | None = None
    description: str | None = None
    counterparty_name: str | None = None
    content_hash: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ReconciliationScoreBreakdown(BaseModel):
    """Deterministic amount/date/reference score details."""

    model_config = ConfigDict(extra="forbid")

    amount_score: int = Field(ge=0, le=50)
    date_score: int = Field(ge=0, le=20)
    reference_score: int = Field(ge=0, le=30)
    total_score: int = Field(ge=0, le=100)
    amount_difference: Decimal | None = None
    matched_signals: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReconciliationCandidate(BaseModel):
    """One deterministic invoice-to-transaction match candidate."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    invoice_number: str | None = None
    score: int = Field(ge=0, le=100)
    confidence: ConfidenceLevel
    score_breakdown: ReconciliationScoreBreakdown
    matched_signals: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


def build_invoice_match_input(
    groups: InvoiceExtractionGroups,
) -> ReconciliationInvoiceInput:
    """Build normalized reconciliation invoice input from extraction groups."""

    metadata = groups.metadata
    totals = groups.totals
    counterparty_names: list[str] = []
    if metadata is not None:
        counterparty_names.extend(
            name
            for name in [metadata.supplier_name, metadata.customer_name]
            if name is not None and name.strip()
        )

    return ReconciliationInvoiceInput(
        invoice_number=metadata.invoice_number if metadata is not None else None,
        issue_date=parse_iso_date(metadata.issue_date)
        if metadata is not None
        else None,
        due_date=parse_iso_date(metadata.due_date) if metadata is not None else None,
        total_amount=parse_decimal(totals.total_amount) if totals is not None else None,
        currency=(totals.currency or metadata.currency)
        if totals is not None and metadata is not None
        else totals.currency
        if totals is not None
        else metadata.currency
        if metadata is not None
        else None,
        counterparty_names=counterparty_names,
        metadata={"source": "invoice_extraction_groups"},
    )


def build_transaction_match_input(
    transaction: StatementTransactionFixture,
) -> ReconciliationTransactionInput:
    """Build normalized reconciliation transaction input from statement fixture."""

    return ReconciliationTransactionInput(
        transaction_id=transaction.external_transaction_id or transaction.content_hash,
        posted_at=transaction.posted_at,
        value_at=transaction.value_at,
        amount=transaction.amount,
        currency=transaction.currency,
        direction=transaction.direction,
        reference=transaction.reference,
        description=" ".join(
            part
            for part in [
                transaction.raw_description,
                transaction.normalized_description,
            ]
            if part
        )
        or None,
        counterparty_name=transaction.counterparty_name,
        content_hash=transaction.content_hash,
        metadata=transaction.metadata,
    )


def generate_reconciliation_candidates(
    *,
    invoice: ReconciliationInvoiceInput,
    transactions: list[ReconciliationTransactionInput],
    min_score: int = DEFAULT_MATCH_THRESHOLD,
) -> list[ReconciliationCandidate]:
    """Generate sorted transaction match candidates above a deterministic threshold."""

    candidates: list[ReconciliationCandidate] = []
    for transaction in transactions:
        breakdown = score_invoice_transaction_match(
            invoice=invoice,
            transaction=transaction,
        )
        if breakdown.total_score < min_score:
            continue
        candidates.append(
            ReconciliationCandidate(
                transaction_id=transaction.transaction_id,
                invoice_number=invoice.invoice_number,
                score=breakdown.total_score,
                confidence=confidence_for_score(breakdown.total_score),
                score_breakdown=breakdown,
                matched_signals=breakdown.matched_signals,
                metadata={
                    "transaction_reference": transaction.reference,
                    "transaction_content_hash": transaction.content_hash,
                    "transaction_amount": str(transaction.amount),
                    "transaction_currency": transaction.currency,
                },
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, candidate.transaction_id),
    )


def score_invoice_transaction_match(
    *,
    invoice: ReconciliationInvoiceInput,
    transaction: ReconciliationTransactionInput,
    amount_tolerance: Decimal = DEFAULT_AMOUNT_TOLERANCE,
) -> ReconciliationScoreBreakdown:
    """Score one invoice-to-transaction pair by amount, date, and reference."""

    notes: list[str] = []
    if currencies_conflict(invoice.currency, transaction.currency):
        return ReconciliationScoreBreakdown(
            amount_score=0,
            date_score=0,
            reference_score=0,
            total_score=0,
            matched_signals=[],
            notes=["currency_mismatch"],
        )

    amount_score, amount_difference, amount_signal = score_amount_match(
        invoice_amount=invoice.total_amount,
        transaction_amount=transaction.amount,
        tolerance=amount_tolerance,
    )
    date_score, date_signal = score_date_match(
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        transaction_date=transaction.posted_at or transaction.value_at,
    )
    reference_score, reference_signal = score_reference_match(
        invoice_number=invoice.invoice_number,
        transaction=transaction,
    )

    matched_signals = [
        signal
        for signal in [amount_signal, date_signal, reference_signal]
        if signal is not None
    ]
    total_score = min(amount_score + date_score + reference_score, 100)
    if not matched_signals:
        notes.append("no_amount_date_or_reference_signal")

    return ReconciliationScoreBreakdown(
        amount_score=amount_score,
        date_score=date_score,
        reference_score=reference_score,
        total_score=total_score,
        amount_difference=amount_difference,
        matched_signals=matched_signals,
        notes=notes,
    )


def score_amount_match(
    *,
    invoice_amount: Decimal | None,
    transaction_amount: Decimal,
    tolerance: Decimal,
) -> tuple[int, Decimal | None, str | None]:
    """Score absolute invoice/transaction amount closeness."""

    if invoice_amount is None:
        return 0, None, None

    difference = abs(abs(transaction_amount) - abs(invoice_amount))
    if difference <= tolerance:
        return 50, difference, "amount_exact"

    one_percent = max(abs(invoice_amount) * Decimal("0.01"), Decimal("1.00"))
    five_percent = max(abs(invoice_amount) * Decimal("0.05"), Decimal("5.00"))
    if difference <= one_percent:
        return 35, difference, "amount_near_1_percent"
    if difference <= five_percent:
        return 15, difference, "amount_near_5_percent"
    return 0, difference, None


def score_date_match(
    *,
    issue_date: date | None,
    due_date: date | None,
    transaction_date: date | None,
) -> tuple[int, str | None]:
    """Score transaction date closeness to invoice issue/due dates."""

    if transaction_date is None:
        return 0, None
    if issue_date is not None and due_date is not None:
        if issue_date <= transaction_date <= due_date:
            return 20, "date_within_invoice_terms"
        if 0 < (transaction_date - due_date).days <= 7:
            return 15, "date_within_7_days_after_due"
        if 0 < (issue_date - transaction_date).days <= 7:
            return 10, "date_within_7_days_before_issue"
    if due_date is not None and abs((transaction_date - due_date).days) <= 7:
        return 12, "date_near_due_date"
    if issue_date is not None and abs((transaction_date - issue_date).days) <= 7:
        return 8, "date_near_issue_date"
    return 0, None


def score_reference_match(
    *,
    invoice_number: str | None,
    transaction: ReconciliationTransactionInput,
) -> tuple[int, str | None]:
    """Score whether transaction text contains invoice reference."""

    normalized_invoice_number = normalize_reference(invoice_number)
    if normalized_invoice_number is None:
        return 0, None

    haystack = normalize_reference(
        " ".join(
            part
            for part in [
                transaction.reference,
                transaction.description,
                transaction.counterparty_name,
            ]
            if part
        )
    )
    if haystack is None:
        return 0, None

    if normalized_invoice_number in haystack:
        return 30, "reference_exact_invoice_number"

    compact_invoice_number = normalized_invoice_number.replace("-", "")
    compact_haystack = haystack.replace("-", "")
    if compact_invoice_number and compact_invoice_number in compact_haystack:
        return 25, "reference_compact_invoice_number"

    return 0, None


def currencies_conflict(
    invoice_currency: str | None,
    transaction_currency: str | None,
) -> bool:
    """Return true when both currencies are known and different."""

    return (
        invoice_currency is not None
        and transaction_currency is not None
        and invoice_currency.upper() != transaction_currency.upper()
    )


def normalize_reference(value: str | None) -> str | None:
    """Normalize free-text references for deterministic matching."""

    if value is None:
        return None
    normalized = " ".join(value.lower().strip().split())
    return normalized or None


def confidence_for_score(score: int) -> ConfidenceLevel:
    """Map deterministic match score to coarse confidence."""

    if score >= 85:
        return ConfidenceLevel.HIGH
    if score >= DEFAULT_MATCH_THRESHOLD:
        return ConfidenceLevel.MEDIUM
    if score > 0:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNKNOWN
