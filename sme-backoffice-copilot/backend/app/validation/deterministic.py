"""Deterministic validators for AI extraction and parser outputs."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.fixtures.loader import StatementParsingFixture, StatementTransactionFixture
from app.workflows.invoice_extraction import InvoiceExtractionGroups

COMMON_CURRENCY_CODES = frozenset(
    {
        "AUD",
        "CAD",
        "EUR",
        "GBP",
        "JPY",
        "SGD",
        "USD",
        "VND",
    }
)


class ValidationSeverity(StrEnum):
    """Severity levels emitted by deterministic validators."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationIssue(BaseModel):
    """One deterministic validation issue."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: ValidationSeverity = ValidationSeverity.ERROR
    field_path: str | None = None
    expected_value: object | None = None
    observed_value: object | None = None
    context: dict[str, object] = Field(default_factory=dict)


class DeterministicValidationResult(BaseModel):
    """Standard result returned by deterministic validators."""

    model_config = ConfigDict(extra="forbid")

    validator_name: str = Field(min_length=1)
    passed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)


class DuplicateDetectionItem(BaseModel):
    """One item used by the generic duplicate detector."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    dedupe_key: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DuplicateDetectionResult(DeterministicValidationResult):
    """Duplicate detector result with duplicate groups."""

    duplicate_groups: dict[str, list[str]] = Field(default_factory=dict)


def validation_result(
    *,
    validator_name: str,
    issues: list[ValidationIssue],
    metrics: dict[str, object] | None = None,
) -> DeterministicValidationResult:
    """Build a standard validation result."""

    return DeterministicValidationResult(
        validator_name=validator_name,
        passed=not any(issue.severity == ValidationSeverity.ERROR for issue in issues),
        issues=issues,
        metrics=metrics or {},
    )


def parse_decimal(value: object) -> Decimal | None:
    """Parse a money-like value into Decimal without guessing invalid input."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def parse_iso_date(value: object) -> date | None:
    """Parse a YYYY-MM-DD date string or pass through date objects."""

    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def validate_invoice_arithmetic(
    groups: InvoiceExtractionGroups,
    *,
    tolerance: Decimal = Decimal("0.01"),
) -> DeterministicValidationResult:
    """Validate extracted invoice subtotal, tax, total, and line totals."""

    issues: list[ValidationIssue] = []
    metrics: dict[str, object] = {}

    if groups.totals is None:
        issues.append(
            ValidationIssue(
                code="ERR_TOTALS_GROUP_MISSING",
                message="Invoice totals group is missing.",
                field_path="groups.totals",
            )
        )
        return validation_result(
            validator_name="invoice_arithmetic_validator",
            issues=issues,
        )

    subtotal = parse_decimal(groups.totals.subtotal_amount)
    tax = parse_decimal(groups.totals.tax_amount)
    total = parse_decimal(groups.totals.total_amount)
    metrics.update(
        {
            "subtotal_amount": str(subtotal) if subtotal is not None else None,
            "tax_amount": str(tax) if tax is not None else None,
            "total_amount": str(total) if total is not None else None,
        }
    )

    for field_path, value in [
        ("groups.totals.subtotal_amount", subtotal),
        ("groups.totals.tax_amount", tax),
        ("groups.totals.total_amount", total),
    ]:
        if value is None:
            issues.append(
                ValidationIssue(
                    code="ERR_AMOUNT_INVALID",
                    message=f"Amount is missing or invalid at {field_path}.",
                    field_path=field_path,
                )
            )

    if subtotal is not None and tax is not None and total is not None:
        expected_total = subtotal + tax
        metrics["expected_total_amount"] = str(expected_total)
        if abs(expected_total - total) > tolerance:
            issues.append(
                ValidationIssue(
                    code="ERR_LOGIC_MATH",
                    message="Invoice subtotal plus tax does not match total.",
                    field_path="groups.totals.total_amount",
                    expected_value=str(expected_total),
                    observed_value=str(total),
                    context={
                        "subtotal_amount": str(subtotal),
                        "tax_amount": str(tax),
                    },
                )
            )

    if groups.table is not None and groups.table.line_items:
        line_totals = [
            parse_decimal(line_item.line_total) for line_item in groups.table.line_items
        ]
        valid_line_totals = [
            line_total for line_total in line_totals if line_total is not None
        ]
        metrics["line_item_count"] = len(groups.table.line_items)
        metrics["line_total_count"] = len(valid_line_totals)
        if len(valid_line_totals) != len(groups.table.line_items):
            issues.append(
                ValidationIssue(
                    code="ERR_LINE_TOTAL_INVALID",
                    message="One or more invoice line totals are invalid.",
                    field_path="groups.table.line_items",
                )
            )
        else:
            line_total_sum = sum(valid_line_totals, Decimal("0"))
            metrics["line_total_sum"] = str(line_total_sum)
            if subtotal is not None:
                subtotal_delta = line_total_sum - subtotal
                metrics["line_total_minus_subtotal"] = str(subtotal_delta)
                if total is not None and abs(line_total_sum - total) <= tolerance:
                    metrics["line_totals_match"] = "total_amount"
                elif abs(subtotal_delta) <= tolerance:
                    metrics["line_totals_match"] = "subtotal_amount"
                elif subtotal_delta > tolerance:
                    metrics["inferred_discount_amount"] = str(subtotal_delta)
                else:
                    issues.append(
                        ValidationIssue(
                            code="ERR_SUBTOTAL_LINE_ITEMS_MISMATCH",
                            message=(
                                "Invoice line totals are less than the extracted "
                                "subtotal."
                            ),
                            field_path="groups.totals.subtotal_amount",
                            expected_value=str(line_total_sum),
                            observed_value=str(subtotal),
                        )
                    )
            elif total is not None and abs(line_total_sum - total) > tolerance:
                issues.append(
                    ValidationIssue(
                        code="ERR_LINE_TOTAL_MISMATCH",
                        message=(
                            "Invoice line totals do not match invoice total and "
                            "subtotal is missing."
                        ),
                        field_path="groups.table.line_items",
                        expected_value=str(total),
                        observed_value=str(line_total_sum),
                    )
                )

    return validation_result(
        validator_name="invoice_arithmetic_validator",
        issues=issues,
        metrics=metrics,
    )


def validate_invoice_dates(
    groups: InvoiceExtractionGroups,
) -> DeterministicValidationResult:
    """Validate invoice issue and due dates."""

    issues: list[ValidationIssue] = []
    if groups.metadata is None:
        issues.append(
            ValidationIssue(
                code="ERR_METADATA_GROUP_MISSING",
                message="Invoice metadata group is missing.",
                field_path="groups.metadata",
            )
        )
        return validation_result(
            validator_name="invoice_date_validator",
            issues=issues,
        )

    issue_date = parse_iso_date(groups.metadata.issue_date)
    due_date = parse_iso_date(groups.metadata.due_date)

    if groups.metadata.issue_date is not None and issue_date is None:
        issues.append(
            ValidationIssue(
                code="ERR_DATE_INVALID",
                message="Invoice issue date is not a valid ISO date.",
                field_path="groups.metadata.issue_date",
                observed_value=groups.metadata.issue_date,
            )
        )
    if groups.metadata.due_date is not None and due_date is None:
        issues.append(
            ValidationIssue(
                code="ERR_DATE_INVALID",
                message="Invoice due date is not a valid ISO date.",
                field_path="groups.metadata.due_date",
                observed_value=groups.metadata.due_date,
            )
        )
    if issue_date is not None and due_date is not None and issue_date > due_date:
        issues.append(
            ValidationIssue(
                code="ERR_DATE_ORDER",
                message="Invoice issue date is after due date.",
                field_path="groups.metadata.due_date",
                expected_value=issue_date.isoformat(),
                observed_value=due_date.isoformat(),
            )
        )

    return validation_result(
        validator_name="invoice_date_validator",
        issues=issues,
        metrics={
            "issue_date": issue_date.isoformat() if issue_date is not None else None,
            "due_date": due_date.isoformat() if due_date is not None else None,
        },
    )


def validate_currency_code(
    currency: str | None,
    *,
    field_path: str = "currency",
    allowed_codes: frozenset[str] = COMMON_CURRENCY_CODES,
) -> DeterministicValidationResult:
    """Validate one currency code against a deterministic allow-list."""

    issues: list[ValidationIssue] = []
    normalized_currency = currency.upper() if isinstance(currency, str) else None

    if normalized_currency is None or len(normalized_currency) != 3:
        issues.append(
            ValidationIssue(
                code="ERR_CURRENCY_INVALID",
                message="Currency code must be a three-letter ISO-style code.",
                field_path=field_path,
                observed_value=currency,
            )
        )
    elif normalized_currency not in allowed_codes:
        issues.append(
            ValidationIssue(
                code="ERR_CURRENCY_UNSUPPORTED",
                message="Currency code is not in the configured allow-list.",
                field_path=field_path,
                observed_value=currency,
                context={"allowed_codes": sorted(allowed_codes)},
            )
        )

    return validation_result(
        validator_name="currency_code_validator",
        issues=issues,
        metrics={"normalized_currency": normalized_currency},
    )


def validate_invoice_currency_consistency(
    groups: InvoiceExtractionGroups,
    *,
    allowed_codes: frozenset[str] = COMMON_CURRENCY_CODES,
) -> DeterministicValidationResult:
    """Validate invoice metadata and totals currencies are valid and consistent."""

    issues: list[ValidationIssue] = []
    metadata_currency = (
        groups.metadata.currency if groups.metadata is not None else None
    )
    totals_currency = groups.totals.currency if groups.totals is not None else None

    for field_path, currency in [
        ("groups.metadata.currency", metadata_currency),
        ("groups.totals.currency", totals_currency),
    ]:
        result = validate_currency_code(
            currency,
            field_path=field_path,
            allowed_codes=allowed_codes,
        )
        issues.extend(result.issues)

    if (
        metadata_currency is not None
        and totals_currency is not None
        and metadata_currency.upper() != totals_currency.upper()
    ):
        issues.append(
            ValidationIssue(
                code="ERR_CURRENCY_MISMATCH",
                message="Invoice metadata currency does not match totals currency.",
                field_path="groups.totals.currency",
                expected_value=metadata_currency.upper(),
                observed_value=totals_currency.upper(),
            )
        )

    return validation_result(
        validator_name="invoice_currency_validator",
        issues=issues,
        metrics={
            "metadata_currency": metadata_currency,
            "totals_currency": totals_currency,
        },
    )


def validate_statement_dates(
    fixture: StatementParsingFixture,
) -> DeterministicValidationResult:
    """Validate statement period and transaction dates."""

    issues: list[ValidationIssue] = []
    start_date = fixture.statement_import.statement_start_date
    end_date = fixture.statement_import.statement_end_date

    if start_date is not None and end_date is not None and start_date > end_date:
        issues.append(
            ValidationIssue(
                code="ERR_STATEMENT_DATE_ORDER",
                message="Statement start date is after end date.",
                field_path="statement_import.statement_end_date",
                expected_value=start_date.isoformat(),
                observed_value=end_date.isoformat(),
            )
        )

    for index, transaction in enumerate(fixture.transactions):
        if (
            start_date is not None
            and transaction.posted_at is not None
            and transaction.posted_at < start_date
        ):
            issues.append(
                transaction_date_issue(
                    code="ERR_TRANSACTION_BEFORE_STATEMENT",
                    transaction=transaction,
                    index=index,
                    boundary=start_date,
                )
            )
        if (
            end_date is not None
            and transaction.posted_at is not None
            and transaction.posted_at > end_date
        ):
            issues.append(
                transaction_date_issue(
                    code="ERR_TRANSACTION_AFTER_STATEMENT",
                    transaction=transaction,
                    index=index,
                    boundary=end_date,
                )
            )

    return validation_result(
        validator_name="statement_date_validator",
        issues=issues,
        metrics={
            "statement_start_date": start_date.isoformat()
            if start_date is not None
            else None,
            "statement_end_date": end_date.isoformat()
            if end_date is not None
            else None,
            "transaction_count": len(fixture.transactions),
        },
    )


def transaction_date_issue(
    *,
    code: str,
    transaction: StatementTransactionFixture,
    index: int,
    boundary: date,
) -> ValidationIssue:
    """Build a statement transaction date issue."""

    return ValidationIssue(
        code=code,
        message="Transaction posted date is outside the statement period.",
        field_path=f"transactions[{index}].posted_at",
        expected_value=boundary.isoformat(),
        observed_value=transaction.posted_at.isoformat()
        if transaction.posted_at is not None
        else None,
        context={"content_hash": transaction.content_hash},
    )


def validate_statement_currency_consistency(
    fixture: StatementParsingFixture,
    *,
    allowed_codes: frozenset[str] = COMMON_CURRENCY_CODES,
) -> DeterministicValidationResult:
    """Validate statement-level and transaction-level currencies."""

    issues: list[ValidationIssue] = []
    expected_currency = (
        fixture.statement_import.currency or fixture.bank_account.currency
    )

    for field_path, currency in [
        ("bank_account.currency", fixture.bank_account.currency),
        ("statement_import.currency", fixture.statement_import.currency),
    ]:
        result = validate_currency_code(
            currency,
            field_path=field_path,
            allowed_codes=allowed_codes,
        )
        issues.extend(result.issues)

    for index, transaction in enumerate(fixture.transactions):
        result = validate_currency_code(
            transaction.currency,
            field_path=f"transactions[{index}].currency",
            allowed_codes=allowed_codes,
        )
        issues.extend(result.issues)
        if (
            expected_currency is not None
            and transaction.currency is not None
            and transaction.currency.upper() != expected_currency.upper()
        ):
            issues.append(
                ValidationIssue(
                    code="ERR_CURRENCY_MISMATCH",
                    message="Transaction currency does not match statement currency.",
                    field_path=f"transactions[{index}].currency",
                    expected_value=expected_currency.upper(),
                    observed_value=transaction.currency.upper(),
                    context={"content_hash": transaction.content_hash},
                )
            )

    return validation_result(
        validator_name="statement_currency_validator",
        issues=issues,
        metrics={
            "expected_currency": expected_currency,
            "transaction_count": len(fixture.transactions),
        },
    )


def detect_duplicates(
    items: list[DuplicateDetectionItem],
    *,
    validator_name: str = "duplicate_detector",
) -> DuplicateDetectionResult:
    """Detect duplicated deterministic keys in a list of items."""

    groups: defaultdict[str, list[str]] = defaultdict(list)
    missing_key_item_ids: list[str] = []
    for item in items:
        if item.dedupe_key is None or not item.dedupe_key.strip():
            missing_key_item_ids.append(item.item_id)
            continue
        groups[item.dedupe_key].append(item.item_id)

    duplicate_groups = {
        key: item_ids for key, item_ids in groups.items() if len(item_ids) > 1
    }
    issues = [
        ValidationIssue(
            code="ERR_DUPLICATE_DETECTED",
            message="Duplicate deterministic key detected.",
            field_path="dedupe_key",
            observed_value=key,
            context={"item_ids": item_ids},
        )
        for key, item_ids in duplicate_groups.items()
    ]
    for item_id in missing_key_item_ids:
        issues.append(
            ValidationIssue(
                code="WARN_DEDUPE_KEY_MISSING",
                message="Item has no deterministic duplicate detection key.",
                severity=ValidationSeverity.WARNING,
                field_path="dedupe_key",
                context={"item_id": item_id},
            )
        )

    result = DuplicateDetectionResult(
        validator_name=validator_name,
        passed=not any(issue.severity == ValidationSeverity.ERROR for issue in issues),
        issues=issues,
        metrics={
            "item_count": len(items),
            "duplicate_group_count": len(duplicate_groups),
            "missing_key_count": len(missing_key_item_ids),
        },
        duplicate_groups=duplicate_groups,
    )
    return result


def validate_transaction_duplicates(
    transactions: list[StatementTransactionFixture],
) -> DuplicateDetectionResult:
    """Detect duplicate statement transactions by content hash."""

    return detect_duplicates(
        [
            DuplicateDetectionItem(
                item_id=transaction.external_transaction_id or f"transaction:{index}",
                dedupe_key=transaction.content_hash,
                metadata={
                    "reference": transaction.reference,
                    "amount": str(transaction.amount),
                },
            )
            for index, transaction in enumerate(transactions)
        ],
        validator_name="transaction_duplicate_detector",
    )
