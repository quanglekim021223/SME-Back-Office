from datetime import date
from decimal import Decimal

from app.fixtures import load_invoice_extraction_fixture, load_statement_parsing_fixture
from app.models.banking import TransactionDirection
from app.reconciliation import (
    DEFAULT_MATCH_THRESHOLD,
    ReconciliationInvoiceInput,
    ReconciliationTransactionInput,
    build_invoice_match_input,
    build_transaction_match_input,
    confidence_for_score,
    generate_reconciliation_candidates,
    score_invoice_transaction_match,
)
from app.workflows import ConfidenceLevel


def test_build_invoice_match_input_from_invoice_fixture() -> None:
    fixture = load_invoice_extraction_fixture()

    invoice = build_invoice_match_input(fixture.extraction_groups)

    assert invoice.invoice_number == "INV-FIX-001"
    assert invoice.issue_date == date(2026, 7, 1)
    assert invoice.due_date == date(2026, 7, 15)
    assert invoice.total_amount == Decimal("110.00")
    assert invoice.currency == "USD"
    assert invoice.counterparty_names == [
        "Northwind Consulting LLC",
        "SME Demo Company",
    ]


def test_build_transaction_match_input_from_statement_fixture() -> None:
    fixture = load_statement_parsing_fixture()

    transaction = build_transaction_match_input(fixture.transactions[0])

    assert transaction.transaction_id == "demo-bank-txn-001"
    assert transaction.posted_at == date(2026, 7, 3)
    assert transaction.amount == Decimal("110.00")
    assert transaction.currency == "USD"
    assert transaction.direction == TransactionDirection.INFLOW
    assert transaction.reference == "INV-FIX-001"
    assert "ACH CREDIT" in transaction.description
    assert transaction.content_hash == "fixture-transaction-hash-001"


def test_score_invoice_transaction_match_uses_amount_date_and_reference() -> None:
    invoice_fixture = load_invoice_extraction_fixture()
    statement_fixture = load_statement_parsing_fixture()
    invoice = build_invoice_match_input(invoice_fixture.extraction_groups)
    transaction = build_transaction_match_input(statement_fixture.transactions[0])

    score = score_invoice_transaction_match(
        invoice=invoice,
        transaction=transaction,
    )

    assert score.amount_score == 50
    assert score.date_score == 20
    assert score.reference_score == 30
    assert score.total_score == 100
    assert score.amount_difference == Decimal("0.00")
    assert score.matched_signals == [
        "amount_exact",
        "date_within_invoice_terms",
        "reference_exact_invoice_number",
    ]


def test_candidate_generator_returns_sorted_matches_above_threshold() -> None:
    invoice_fixture = load_invoice_extraction_fixture()
    statement_fixture = load_statement_parsing_fixture()
    invoice = build_invoice_match_input(invoice_fixture.extraction_groups)
    transactions = [
        build_transaction_match_input(transaction)
        for transaction in statement_fixture.transactions
    ]

    candidates = generate_reconciliation_candidates(
        invoice=invoice,
        transactions=transactions,
        min_score=DEFAULT_MATCH_THRESHOLD,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.transaction_id == "demo-bank-txn-001"
    assert candidate.invoice_number == "INV-FIX-001"
    assert candidate.score == 100
    assert candidate.confidence == ConfidenceLevel.HIGH
    assert candidate.metadata["transaction_reference"] == "INV-FIX-001"


def test_candidate_generator_excludes_low_score_transactions() -> None:
    invoice = ReconciliationInvoiceInput(
        invoice_number="INV-LOW-001",
        issue_date=date(2026, 7, 1),
        due_date=date(2026, 7, 15),
        total_amount=Decimal("999.00"),
        currency="USD",
    )
    transaction = ReconciliationTransactionInput(
        transaction_id="txn-low",
        posted_at=date(2026, 7, 3),
        amount=Decimal("10.00"),
        currency="USD",
        reference="NO-MATCH",
        description="unrelated transfer",
    )

    score = score_invoice_transaction_match(invoice=invoice, transaction=transaction)
    candidates = generate_reconciliation_candidates(
        invoice=invoice,
        transactions=[transaction],
    )

    assert score.total_score == 20
    assert score.matched_signals == ["date_within_invoice_terms"]
    assert candidates == []


def test_amount_score_handles_near_matches() -> None:
    invoice = ReconciliationInvoiceInput(
        invoice_number="INV-NEAR-001",
        total_amount=Decimal("100.00"),
        currency="USD",
    )
    transaction = ReconciliationTransactionInput(
        transaction_id="txn-near",
        amount=Decimal("100.75"),
        currency="USD",
    )

    score = score_invoice_transaction_match(invoice=invoice, transaction=transaction)

    assert score.amount_score == 35
    assert score.amount_difference == Decimal("0.75")
    assert score.matched_signals == ["amount_near_1_percent"]


def test_date_score_handles_payment_after_due_date() -> None:
    invoice = ReconciliationInvoiceInput(
        invoice_number="INV-DATE-001",
        issue_date=date(2026, 7, 1),
        due_date=date(2026, 7, 15),
        total_amount=Decimal("100.00"),
        currency="USD",
    )
    transaction = ReconciliationTransactionInput(
        transaction_id="txn-date",
        posted_at=date(2026, 7, 20),
        amount=Decimal("100.00"),
        currency="USD",
    )

    score = score_invoice_transaction_match(invoice=invoice, transaction=transaction)

    assert score.date_score == 15
    assert "date_within_7_days_after_due" in score.matched_signals


def test_reference_score_handles_compact_invoice_number() -> None:
    invoice = ReconciliationInvoiceInput(
        invoice_number="INV-FIX-001",
        total_amount=Decimal("110.00"),
        currency="USD",
    )
    transaction = ReconciliationTransactionInput(
        transaction_id="txn-reference",
        amount=Decimal("110.00"),
        currency="USD",
        reference="INVFIX001",
    )

    score = score_invoice_transaction_match(invoice=invoice, transaction=transaction)

    assert score.reference_score == 25
    assert "reference_compact_invoice_number" in score.matched_signals


def test_currency_mismatch_returns_zero_score() -> None:
    invoice = ReconciliationInvoiceInput(
        invoice_number="INV-CURRENCY-001",
        total_amount=Decimal("110.00"),
        currency="USD",
    )
    transaction = ReconciliationTransactionInput(
        transaction_id="txn-currency",
        posted_at=date(2026, 7, 3),
        amount=Decimal("110.00"),
        currency="EUR",
        reference="INV-CURRENCY-001",
    )

    score = score_invoice_transaction_match(invoice=invoice, transaction=transaction)

    assert score.total_score == 0
    assert score.notes == ["currency_mismatch"]


def test_confidence_for_score_uses_stable_thresholds() -> None:
    assert confidence_for_score(90) == ConfidenceLevel.HIGH
    assert confidence_for_score(70) == ConfidenceLevel.MEDIUM
    assert confidence_for_score(30) == ConfidenceLevel.LOW
    assert confidence_for_score(0) == ConfidenceLevel.UNKNOWN
