from decimal import Decimal

from app.fixtures import load_invoice_extraction_fixture, load_statement_parsing_fixture
from app.fixtures.loader import StatementParsingFixture
from app.validation import (
    DuplicateDetectionItem,
    ValidationSeverity,
    detect_duplicates,
    parse_decimal,
    parse_iso_date,
    validate_currency_code,
    validate_invoice_arithmetic,
    validate_invoice_currency_consistency,
    validate_invoice_dates,
    validate_statement_currency_consistency,
    validate_statement_dates,
    validate_transaction_duplicates,
)
from app.workflows import InvoiceExtractionGroups


def test_parse_decimal_accepts_money_like_values_without_guessing_invalid_input() -> (
    None
):
    assert parse_decimal("1,234.50") == Decimal("1234.50")
    assert parse_decimal(110) == Decimal("110")
    assert parse_decimal("not money") is None
    assert parse_decimal(None) is None


def test_parse_iso_date_accepts_iso_dates_only() -> None:
    assert parse_iso_date("2026-07-01").isoformat() == "2026-07-01"
    assert parse_iso_date("07/01/2026") is None
    assert parse_iso_date(None) is None


def test_invoice_arithmetic_validator_passes_fixture_output() -> None:
    fixture = load_invoice_extraction_fixture()

    result = validate_invoice_arithmetic(fixture.extraction_groups)

    assert result.passed is True
    assert result.issues == []
    assert result.metrics["expected_total_amount"] == "110.00"
    assert result.metrics["line_total_sum"] == "110.00"


def test_invoice_arithmetic_validator_detects_total_mismatch() -> None:
    fixture = load_invoice_extraction_fixture()
    payload = fixture.extraction_groups.model_dump(mode="json")
    payload["totals"]["total_amount"] = "120.00"
    groups = InvoiceExtractionGroups.model_validate(payload)

    result = validate_invoice_arithmetic(groups)

    assert result.passed is False
    assert {issue.code for issue in result.issues} == {
        "ERR_LOGIC_MATH",
        "ERR_LINE_TOTAL_MISMATCH",
    }
    assert result.issues[0].severity == ValidationSeverity.ERROR


def test_invoice_arithmetic_validator_detects_invalid_amounts() -> None:
    fixture = load_invoice_extraction_fixture()
    payload = fixture.extraction_groups.model_dump(mode="json")
    payload["totals"]["tax_amount"] = "ten dollars"
    groups = InvoiceExtractionGroups.model_validate(payload)

    result = validate_invoice_arithmetic(groups)

    assert result.passed is False
    assert any(issue.code == "ERR_AMOUNT_INVALID" for issue in result.issues)


def test_invoice_date_validator_passes_fixture_output() -> None:
    fixture = load_invoice_extraction_fixture()

    result = validate_invoice_dates(fixture.extraction_groups)

    assert result.passed is True
    assert result.metrics == {
        "issue_date": "2026-07-01",
        "due_date": "2026-07-15",
    }


def test_invoice_date_validator_detects_invalid_order_and_format() -> None:
    fixture = load_invoice_extraction_fixture()
    payload = fixture.extraction_groups.model_dump(mode="json")
    payload["metadata"]["issue_date"] = "2026-07-20"
    payload["metadata"]["due_date"] = "2026-07-15"
    groups = InvoiceExtractionGroups.model_validate(payload)

    order_result = validate_invoice_dates(groups)

    assert order_result.passed is False
    assert order_result.issues[0].code == "ERR_DATE_ORDER"

    payload["metadata"]["issue_date"] = "July 20, 2026"
    invalid_result = validate_invoice_dates(
        InvoiceExtractionGroups.model_validate(payload)
    )

    assert invalid_result.passed is False
    assert any(issue.code == "ERR_DATE_INVALID" for issue in invalid_result.issues)


def test_currency_code_validator_accepts_common_upper_or_lowercase_codes() -> None:
    usd_result = validate_currency_code("USD")
    vnd_result = validate_currency_code("vnd")

    assert usd_result.passed is True
    assert usd_result.metrics["normalized_currency"] == "USD"
    assert vnd_result.passed is True
    assert vnd_result.metrics["normalized_currency"] == "VND"


def test_currency_code_validator_rejects_bad_or_unsupported_codes() -> None:
    invalid_result = validate_currency_code("US")
    unsupported_result = validate_currency_code("ZZZ")

    assert invalid_result.passed is False
    assert invalid_result.issues[0].code == "ERR_CURRENCY_INVALID"
    assert unsupported_result.passed is False
    assert unsupported_result.issues[0].code == "ERR_CURRENCY_UNSUPPORTED"


def test_invoice_currency_validator_detects_mismatch() -> None:
    fixture = load_invoice_extraction_fixture()
    payload = fixture.extraction_groups.model_dump(mode="json")
    payload["totals"]["currency"] = "EUR"
    groups = InvoiceExtractionGroups.model_validate(payload)

    result = validate_invoice_currency_consistency(groups)

    assert result.passed is False
    assert any(issue.code == "ERR_CURRENCY_MISMATCH" for issue in result.issues)


def test_statement_date_validator_passes_fixture_output() -> None:
    fixture = load_statement_parsing_fixture()

    result = validate_statement_dates(fixture)

    assert result.passed is True
    assert result.metrics["transaction_count"] == 3


def test_statement_date_validator_detects_transactions_outside_period() -> None:
    fixture = load_statement_parsing_fixture()
    payload = fixture.model_dump(mode="json")
    payload["transactions"][0]["posted_at"] = "2026-08-01"
    modified_fixture = StatementParsingFixture.model_validate(payload)

    result = validate_statement_dates(modified_fixture)

    assert result.passed is False
    assert result.issues[0].code == "ERR_TRANSACTION_AFTER_STATEMENT"
    assert result.issues[0].field_path == "transactions[0].posted_at"


def test_statement_currency_validator_passes_fixture_output() -> None:
    fixture = load_statement_parsing_fixture()

    result = validate_statement_currency_consistency(fixture)

    assert result.passed is True
    assert result.metrics["expected_currency"] == "USD"


def test_statement_currency_validator_detects_transaction_mismatch() -> None:
    fixture = load_statement_parsing_fixture()
    payload = fixture.model_dump(mode="json")
    payload["transactions"][1]["currency"] = "EUR"
    modified_fixture = StatementParsingFixture.model_validate(payload)

    result = validate_statement_currency_consistency(modified_fixture)

    assert result.passed is False
    assert any(issue.code == "ERR_CURRENCY_MISMATCH" for issue in result.issues)


def test_duplicate_detector_passes_unique_keys_and_warns_missing_keys() -> None:
    result = detect_duplicates(
        [
            DuplicateDetectionItem(item_id="doc-1", dedupe_key="hash-1"),
            DuplicateDetectionItem(item_id="doc-2", dedupe_key="hash-2"),
            DuplicateDetectionItem(item_id="doc-3", dedupe_key=None),
        ]
    )

    assert result.passed is True
    assert result.duplicate_groups == {}
    assert result.metrics["missing_key_count"] == 1
    assert result.issues[0].severity == ValidationSeverity.WARNING


def test_duplicate_detector_detects_duplicate_keys() -> None:
    result = detect_duplicates(
        [
            DuplicateDetectionItem(item_id="doc-1", dedupe_key="hash-1"),
            DuplicateDetectionItem(item_id="doc-2", dedupe_key="hash-1"),
        ]
    )

    assert result.passed is False
    assert result.duplicate_groups == {"hash-1": ["doc-1", "doc-2"]}
    assert result.issues[0].code == "ERR_DUPLICATE_DETECTED"


def test_transaction_duplicate_detector_uses_content_hash() -> None:
    fixture = load_statement_parsing_fixture()
    transactions = [
        *fixture.transactions,
        fixture.transactions[0].model_copy(
            update={"external_transaction_id": "demo-bank-txn-duplicate"}
        ),
    ]

    result = validate_transaction_duplicates(transactions)

    assert result.passed is False
    assert result.duplicate_groups == {
        "fixture-transaction-hash-001": [
            "demo-bank-txn-001",
            "demo-bank-txn-duplicate",
        ]
    }
