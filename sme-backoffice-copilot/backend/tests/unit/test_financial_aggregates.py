from datetime import date
from decimal import Decimal

from app.fixtures import load_statement_parsing_fixture
from app.insights import (
    DeterministicFinancialAggregateService,
    build_financial_transaction_input,
    normalized_signed_amount,
)
from app.models.accounting import CategoryType
from app.models.banking import TransactionDirection


def test_financial_aggregate_service_computes_fixture_cashflow() -> None:
    fixture = load_statement_parsing_fixture()

    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        fixture
    )

    assert report.period_start == date(2026, 7, 1)
    assert report.period_end == date(2026, 7, 31)
    assert report.currency == "USD"
    assert report.opening_balance == Decimal("1000.00")
    assert report.closing_balance == Decimal("1215.00")
    assert report.expected_closing_balance == Decimal("1215.00")
    assert report.closing_balance_variance == Decimal("0.00")
    assert report.transaction_count == 3
    assert report.inflow_count == 2
    assert report.outflow_count == 1
    assert report.total_inflow == Decimal("260.00")
    assert report.total_outflow == Decimal("-45.00")
    assert report.total_outflow_abs == Decimal("45.00")
    assert report.net_change == Decimal("215.00")


def test_financial_aggregate_service_tracks_source_evidence_refs() -> None:
    fixture = load_statement_parsing_fixture()

    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        fixture
    )

    assert report.transaction_evidence_refs == [
        "statement_transaction:demo-bank-txn-001",
        "statement_transaction:demo-bank-txn-002",
        "statement_transaction:demo-bank-txn-003",
    ]
    assert report.inflow_evidence_refs == [
        "statement_transaction:demo-bank-txn-001",
        "statement_transaction:demo-bank-txn-003",
    ]
    assert report.outflow_evidence_refs == ["statement_transaction:demo-bank-txn-002"]
    assert report.largest_inflow_ref == "statement_transaction:demo-bank-txn-003"
    assert report.largest_inflow_amount == Decimal("150.00")
    assert report.largest_outflow_ref == "statement_transaction:demo-bank-txn-002"
    assert report.largest_outflow_amount == Decimal("45.00")


def test_financial_aggregate_service_computes_category_totals() -> None:
    fixture = load_statement_parsing_fixture()

    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        fixture
    )

    category_totals = {
        aggregate.category_code: aggregate for aggregate in report.category_totals
    }

    assert category_totals["professional_services"].total_amount == Decimal("150.00")
    assert (
        category_totals["professional_services"].category_type == CategoryType.REVENUE
    )
    assert category_totals["sales_revenue"].total_amount == Decimal("110.00")
    assert category_totals["software_subscription"].total_amount == Decimal("-45.00")
    assert category_totals["software_subscription"].absolute_amount == Decimal("45.00")


def test_build_financial_transaction_input_adds_classification_metadata() -> None:
    fixture = load_statement_parsing_fixture()

    transaction_input = build_financial_transaction_input(fixture.transactions[1])

    assert transaction_input.transaction_id == "demo-bank-txn-002"
    assert transaction_input.signed_amount == Decimal("-45.00")
    assert transaction_input.category_code == "software_subscription"
    assert transaction_input.category_type == CategoryType.EXPENSE
    assert transaction_input.evidence_ref == "statement_transaction:demo-bank-txn-002"
    assert transaction_input.metadata["content_hash"] == "fixture-transaction-hash-002"
    assert transaction_input.metadata["matched_rule_ids"] == [
        "expense_software_subscription"
    ]


def test_normalized_signed_amount_respects_transaction_direction() -> None:
    assert normalized_signed_amount(
        amount=Decimal("-42.00"),
        direction=TransactionDirection.INFLOW,
    ) == Decimal("42.00")
    assert normalized_signed_amount(
        amount=Decimal("42.00"),
        direction=TransactionDirection.OUTFLOW,
    ) == Decimal("-42.00")
    assert normalized_signed_amount(
        amount=Decimal("-42.00"),
        direction=TransactionDirection.UNKNOWN,
    ) == Decimal("-42.00")
