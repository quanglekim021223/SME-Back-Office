from decimal import Decimal

import pytest

from app.fixtures import (
    FixtureKind,
    FixtureLoadError,
    FixtureNotFoundError,
    list_fixture_names,
    load_invoice_extraction_fixture,
    load_json_fixture,
    load_statement_parsing_fixture,
)
from app.models.banking import (
    BankAccountType,
    StatementImportStatus,
    TransactionDirection,
    TransactionStatus,
)
from app.workflows import ConfidenceLevel, InvoiceExtractionStatus


def test_invoice_extraction_fixture_loads_and_matches_contracts() -> None:
    fixture = load_invoice_extraction_fixture()
    groups = fixture.extraction_groups

    assert fixture.fixture_name == "sample_invoice_extraction"
    assert fixture.source_document_type == "invoice"
    assert "Invoice #INV-FIX-001" in fixture.ocr_text
    assert groups.missing_group_names == []
    assert groups.metadata is not None
    assert groups.metadata.extraction_status == InvoiceExtractionStatus.EXTRACTED
    assert groups.metadata.invoice_number == "INV-FIX-001"
    assert groups.metadata.currency == "USD"
    assert groups.table is not None
    assert len(groups.table.line_items) == 1
    assert groups.table.line_items[0].description == "Advisory retainer"
    assert groups.totals is not None
    assert groups.totals.subtotal_amount == "100.00"
    assert groups.totals.tax_amount == "10.00"
    assert groups.totals.total_amount == "110.00"
    assert fixture.expected_validation["subtotal_plus_tax_equals_total"] is True


def test_statement_parsing_fixture_loads_and_matches_banking_contracts() -> None:
    fixture = load_statement_parsing_fixture()

    assert fixture.fixture_name == "sample_statement_parsing"
    assert fixture.source_document_type == "bank_statement"
    assert fixture.bank_account.institution_name == "Demo Bank"
    assert fixture.bank_account.account_type == BankAccountType.CHECKING
    assert fixture.bank_account.currency == "USD"
    assert fixture.statement_import.status == StatementImportStatus.PARSED
    assert fixture.statement_import.row_count == len(fixture.transactions)
    assert fixture.statement_import.opening_balance == Decimal("1000.00")
    assert fixture.statement_import.closing_balance == Decimal("1215.00")

    first_transaction = fixture.transactions[0]
    assert first_transaction.status == TransactionStatus.POSTED
    assert first_transaction.direction == TransactionDirection.INFLOW
    assert first_transaction.reference == "INV-FIX-001"
    assert first_transaction.amount == Decimal("110.00")
    assert first_transaction.confidence == ConfidenceLevel.HIGH

    total_amount = sum(transaction.amount for transaction in fixture.transactions)
    assert total_amount == Decimal("215.00")
    assert fixture.expected_metrics["net_change"] == "215.00"


def test_fixture_names_are_listable_by_kind() -> None:
    assert "sample_invoice_extraction" in list_fixture_names(
        FixtureKind.INVOICE_EXTRACTION
    )
    assert "sample_statement_parsing" in list_fixture_names(
        FixtureKind.STATEMENT_PARSING
    )


def test_raw_json_fixture_loader_returns_payload_dict() -> None:
    payload = load_json_fixture(
        kind=FixtureKind.INVOICE_EXTRACTION,
        name="sample_invoice_extraction",
    )

    assert payload["schema_version"] == "fixture.invoice-extraction.v1"
    assert payload["fixture_name"] == "sample_invoice_extraction"


def test_fixture_loader_rejects_unsafe_names() -> None:
    with pytest.raises(FixtureLoadError):
        load_json_fixture(
            kind=FixtureKind.INVOICE_EXTRACTION,
            name="../sample_invoice_extraction",
        )

    with pytest.raises(FixtureLoadError):
        load_json_fixture(
            kind=FixtureKind.INVOICE_EXTRACTION,
            name="sample_invoice_extraction.json",
        )


def test_fixture_loader_reports_missing_fixture() -> None:
    with pytest.raises(FixtureNotFoundError):
        load_json_fixture(
            kind=FixtureKind.INVOICE_EXTRACTION,
            name="missing_fixture",
        )
