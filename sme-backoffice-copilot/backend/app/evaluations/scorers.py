"""Deterministic evaluation scorers for labelled SME finance datasets."""

from __future__ import annotations

import csv
from collections.abc import Collection, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from io import StringIO

from pydantic import BaseModel, ConfigDict, Field

from app.classification.rules import CategoryClassificationResult
from app.evaluations.datasets import (
    ExpectedClassificationLabel,
    ExpectedClassificationRecordLabel,
    ExpectedExtractionLabel,
    ExpectedInvoiceLineItemLabel,
    ExpectedReconciliationLabel,
    ExpectedReconciliationMatchLabel,
    ExpectedReviewRoutingLabel,
    ExpectedReviewTaskLabel,
)
from app.insights import FinancialAggregateReport, GroundedInsight
from app.models.banking import TransactionDirection
from app.models.operations import ReviewTaskPriority, ReviewTaskType
from app.reconciliation.deterministic import ReconciliationCandidate
from app.validation import parse_decimal
from app.workflows.contracts import ConfidenceLevel
from app.workflows.invoice_extraction import (
    InvoiceExtractionGroups,
    InvoiceLineItemCandidate,
)


class EvaluationCheck(BaseModel):
    """One field-level evaluation check."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    passed: bool
    expected: str | None = None
    actual: str | None = None
    message: str | None = None


class EvaluationScore(BaseModel):
    """Standard score emitted by deterministic evaluation scorers."""

    model_config = ConfigDict(extra="forbid")

    scorer_name: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    passed_checks: int = Field(ge=0)
    total_checks: int = Field(ge=0)
    checks: list[EvaluationCheck] = Field(default_factory=list)
    metrics: dict[str, object] = Field(default_factory=dict)


class StatementParsingExpectedRow(BaseModel):
    """Expected normalized bank statement row used by parsing evaluation."""

    model_config = ConfigDict(extra="forbid")

    posted_at: str = Field(min_length=1)
    value_at: str | None = None
    direction: TransactionDirection
    description: str = Field(min_length=1)
    counterparty: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    running_balance: Decimal | None = None


class ReviewRoutingActualTask(BaseModel):
    """Actual review task emitted by a workflow for review-routing evaluation."""

    model_config = ConfigDict(extra="forbid")

    task_type: ReviewTaskType
    target_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    priority: ReviewTaskPriority = ReviewTaskPriority.NORMAL


def score_extraction(
    *,
    expected: ExpectedExtractionLabel,
    actual: InvoiceExtractionGroups,
) -> EvaluationScore:
    """Score invoice extraction output against expected invoice labels."""

    checks: list[EvaluationCheck] = []
    metadata = actual.metadata
    totals = actual.totals
    table = actual.table

    if metadata is None:
        checks.append(
            failed_check(
                "metadata_group_present",
                expected="present",
                actual="missing",
            )
        )
    else:
        checks.extend(
            [
                check_text(
                    "invoice_number",
                    expected.invoice_number,
                    metadata.invoice_number,
                ),
                check_text(
                    "supplier_name", expected.supplier_name, metadata.supplier_name
                ),
                check_text(
                    "supplier_tax_id",
                    expected.supplier_tax_id,
                    metadata.supplier_tax_id,
                ),
                check_text(
                    "customer_name", expected.customer_name, metadata.customer_name
                ),
                check_text(
                    "customer_tax_id",
                    expected.customer_tax_id,
                    metadata.customer_tax_id,
                ),
                check_text("issue_date", expected.issue_date, metadata.issue_date),
                check_text("due_date", expected.due_date, metadata.due_date),
                check_text("metadata_currency", expected.currency, metadata.currency),
            ]
        )

    if totals is None:
        checks.append(
            failed_check(
                "totals_group_present",
                expected="present",
                actual="missing",
            )
        )
    else:
        checks.extend(
            [
                check_decimal(
                    "subtotal_amount",
                    expected.subtotal_amount,
                    totals.subtotal_amount,
                    tolerance=expected.amount_tolerance,
                ),
                check_decimal(
                    "tax_amount",
                    expected.tax_amount,
                    totals.tax_amount,
                    tolerance=expected.amount_tolerance,
                ),
                check_decimal(
                    "total_amount",
                    expected.total_amount,
                    totals.total_amount,
                    tolerance=expected.amount_tolerance,
                ),
                check_text("totals_currency", expected.currency, totals.currency),
            ]
        )

    expected_line_count = len(expected.line_items)
    actual_line_items = table.line_items if table is not None else []
    checks.append(
        check_exact(
            "line_item_count",
            str(expected_line_count),
            str(len(actual_line_items)),
        )
    )
    actual_by_line_number = {
        line_item.line_number: line_item for line_item in actual_line_items
    }
    for expected_line_item in expected.line_items:
        checks.extend(
            score_line_item(
                expected=expected_line_item,
                actual=actual_by_line_number.get(expected_line_item.line_number),
                amount_tolerance=expected.amount_tolerance,
            )
        )

    return build_score(
        scorer_name="extraction_scorer",
        checks=checks,
        metrics={
            "case_id": expected.case_id,
            "required_fields": expected.required_fields,
            "expected_line_item_count": expected_line_count,
            "actual_line_item_count": len(actual_line_items),
        },
    )


def score_statement_parsing(
    *,
    expected_rows: Sequence[StatementParsingExpectedRow],
    actual_rows: Sequence[StatementParsingExpectedRow],
    amount_tolerance: Decimal = Decimal("0.01"),
) -> EvaluationScore:
    """Score parsed bank statement rows against expected normalized rows."""

    checks: list[EvaluationCheck] = [
        check_exact(
            "statement_row_count", str(len(expected_rows)), str(len(actual_rows))
        )
    ]
    actual_by_reference = {row.reference: row for row in actual_rows}

    for expected_row in expected_rows:
        actual_row = actual_by_reference.get(expected_row.reference)
        if actual_row is None:
            checks.append(
                failed_check(
                    f"statement_row[{expected_row.reference}].present",
                    expected="present",
                    actual="missing",
                )
            )
            continue

        checks.extend(
            [
                check_text(
                    f"statement_row[{expected_row.reference}].posted_at",
                    expected_row.posted_at,
                    actual_row.posted_at,
                ),
                check_text(
                    f"statement_row[{expected_row.reference}].value_at",
                    expected_row.value_at,
                    actual_row.value_at,
                ),
                check_exact(
                    f"statement_row[{expected_row.reference}].direction",
                    expected_row.direction.value,
                    actual_row.direction.value,
                ),
                check_text(
                    f"statement_row[{expected_row.reference}].counterparty",
                    expected_row.counterparty,
                    actual_row.counterparty,
                ),
                check_decimal(
                    f"statement_row[{expected_row.reference}].amount",
                    expected_row.amount,
                    actual_row.amount,
                    tolerance=amount_tolerance,
                ),
                check_text(
                    f"statement_row[{expected_row.reference}].currency",
                    expected_row.currency,
                    actual_row.currency,
                ),
                check_decimal(
                    f"statement_row[{expected_row.reference}].running_balance",
                    expected_row.running_balance,
                    actual_row.running_balance,
                    tolerance=amount_tolerance,
                ),
            ]
        )

    return build_score(
        scorer_name="statement_parsing_scorer",
        checks=checks,
        metrics={
            "expected_row_count": len(expected_rows),
            "actual_row_count": len(actual_rows),
        },
    )


def parse_statement_csv_expected_rows(
    csv_text: str,
) -> list[StatementParsingExpectedRow]:
    """Parse a de-identified statement CSV fixture into expected rows."""

    reader = csv.DictReader(StringIO(csv_text))
    rows: list[StatementParsingExpectedRow] = []
    for raw_row in reader:
        amount = parse_decimal(raw_row.get("amount"))
        if amount is None:
            raise ValueError(f"Invalid statement amount: {raw_row.get('amount')!r}")
        running_balance = parse_decimal(raw_row.get("running_balance"))
        rows.append(
            StatementParsingExpectedRow(
                posted_at=required_csv_value(raw_row, "posted_at"),
                value_at=raw_row.get("value_at") or None,
                direction=TransactionDirection(
                    required_csv_value(raw_row, "direction")
                ),
                description=required_csv_value(raw_row, "description"),
                counterparty=required_csv_value(raw_row, "counterparty"),
                reference=required_csv_value(raw_row, "reference"),
                amount=amount,
                currency=required_csv_value(raw_row, "currency"),
                running_balance=running_balance,
            )
        )
    return rows


def score_classification(
    *,
    expected: ExpectedClassificationLabel,
    actual_by_source_ref: Mapping[str, CategoryClassificationResult],
) -> EvaluationScore:
    """Score category classification proposals against expected labels."""

    checks: list[EvaluationCheck] = [
        check_exact(
            "classification_record_count",
            str(len(expected.records)),
            str(len(actual_by_source_ref)),
        )
    ]
    for expected_record in expected.records:
        actual = actual_by_source_ref.get(expected_record.source_ref)
        if actual is None:
            checks.append(
                failed_check(
                    f"classification[{expected_record.source_ref}].present",
                    expected="present",
                    actual="missing",
                )
            )
            continue

        checks.extend(score_classification_record(expected_record, actual))

    return build_score(
        scorer_name="classification_scorer",
        checks=checks,
        metrics={
            "case_id": expected.case_id,
            "expected_record_count": len(expected.records),
            "actual_record_count": len(actual_by_source_ref),
        },
    )


def score_reconciliation(
    *,
    expected: ExpectedReconciliationLabel,
    actual_candidates: Sequence[ReconciliationCandidate],
) -> EvaluationScore:
    """Score reconciliation candidates against expected match labels."""

    checks: list[EvaluationCheck] = []
    for expected_match in expected.expected_matches:
        actual = find_reconciliation_candidate(
            expected_match=expected_match,
            candidates=actual_candidates,
        )
        if actual is None:
            checks.append(
                failed_check(
                    f"reconciliation[{expected_match.invoice_number}:{expected_match.transaction_reference}].present",
                    expected="present",
                    actual="missing",
                )
            )
            continue

        checks.extend(score_reconciliation_match(expected_match, actual))

    for unmatched_ref in expected.expected_unmatched_transaction_refs:
        checks.append(
            check_unmatched_reference_absent(
                unmatched_ref=unmatched_ref,
                actual_candidates=actual_candidates,
            )
        )

    return build_score(
        scorer_name="reconciliation_scorer",
        checks=checks,
        metrics={
            "case_id": expected.case_id,
            "expected_match_count": len(expected.expected_matches),
            "actual_candidate_count": len(actual_candidates),
            "expected_unmatched_transaction_refs": (
                expected.expected_unmatched_transaction_refs
            ),
        },
    )


def score_insight_groundedness(
    *,
    report: FinancialAggregateReport,
    insights: Sequence[GroundedInsight],
) -> EvaluationScore:
    """Score whether generated insights are grounded in source aggregate data."""

    source_metrics = report_metric_map(report)
    allowed_evidence_refs = report_evidence_refs(report)
    checks: list[EvaluationCheck] = [
        check_minimum_int("insight_count", 1, len(insights))
    ]

    for index, insight in enumerate(insights, start=1):
        prefix = f"insight[{index}:{insight.insight_type.value}]"
        checks.extend(
            [
                check_minimum_int(
                    f"{prefix}.evidence_ref_count",
                    1,
                    len(insight.evidence_refs),
                ),
                check_minimum_int(
                    f"{prefix}.source_metric_key_count",
                    1,
                    len(insight.source_metric_keys),
                ),
                check_minimum_int(
                    f"{prefix}.metric_count",
                    1,
                    len(insight.metrics),
                ),
            ]
        )

        for evidence_ref in insight.evidence_refs:
            checks.append(
                check_collection_member(
                    f"{prefix}.evidence_ref[{evidence_ref}]",
                    expected_collection=allowed_evidence_refs,
                    actual=evidence_ref,
                    missing_message=(
                        "Insight cites evidence not present in the source report."
                    ),
                )
            )

        for metric_key in insight.source_metric_keys:
            source_value = source_metrics.get(metric_key)
            actual_value = insight.metrics.get(metric_key)
            if metric_key not in source_metrics:
                checks.append(
                    failed_check(
                        f"{prefix}.source_metric[{metric_key}].available",
                        expected="source_metric_present",
                        actual="missing",
                    )
                )
                continue
            if metric_key not in insight.metrics:
                checks.append(
                    failed_check(
                        f"{prefix}.metric[{metric_key}].present",
                        expected="present",
                        actual="missing",
                    )
                )
                continue
            checks.append(
                check_metric_value(
                    f"{prefix}.metric[{metric_key}]",
                    expected=source_value,
                    actual=actual_value,
                )
            )

        for metric_key, actual_value in insight.metrics.items():
            if metric_key not in source_metrics:
                checks.append(
                    failed_check(
                        f"{prefix}.metric[{metric_key}].grounded",
                        expected="known_source_metric",
                        actual="unsupported_metric",
                    )
                )
                continue
            checks.append(
                check_metric_value(
                    f"{prefix}.metric[{metric_key}].grounded",
                    expected=source_metrics[metric_key],
                    actual=actual_value,
                )
            )

    return build_score(
        scorer_name="insight_groundedness_scorer",
        checks=checks,
        metrics={
            "source_report_schema_version": report.schema_version,
            "source_transaction_count": report.transaction_count,
            "insight_count": len(insights),
            "allowed_evidence_ref_count": len(allowed_evidence_refs),
        },
    )


def score_review_routing(
    *,
    expected: ExpectedReviewRoutingLabel,
    actual_tasks: Sequence[ReviewRoutingActualTask],
) -> EvaluationScore:
    """Score human-review routing decisions against expected review labels."""

    expected_by_key = {review_task_key(task): task for task in expected.expected_tasks}
    actual_by_key = {review_task_key(task): task for task in actual_tasks}
    checks: list[EvaluationCheck] = [
        check_exact(
            "review_routing.should_create_review_task",
            expected.should_create_review_task,
            bool(actual_tasks),
        ),
        check_exact(
            "review_routing.task_count",
            len(expected.expected_tasks),
            len(actual_tasks),
        ),
    ]

    for expected_task in expected.expected_tasks:
        key = review_task_key(expected_task)
        actual_task = actual_by_key.get(key)
        if actual_task is None:
            checks.append(
                failed_check(
                    f"review_routing.task[{key}].present",
                    expected="present",
                    actual="missing",
                )
            )
            continue
        checks.append(
            check_exact(
                f"review_routing.task[{key}].priority",
                expected_task.priority.value,
                actual_task.priority.value,
            )
        )

    for actual_task in actual_tasks:
        key = review_task_key(actual_task)
        if key not in expected_by_key:
            checks.append(
                failed_check(
                    f"review_routing.task[{key}].expected",
                    expected="known_expected_task",
                    actual="unexpected_task",
                )
            )

    return build_score(
        scorer_name="review_routing_scorer",
        checks=checks,
        metrics={
            "case_id": expected.case_id,
            "expected_task_count": len(expected.expected_tasks),
            "actual_task_count": len(actual_tasks),
        },
    )


def score_line_item(
    *,
    expected: ExpectedInvoiceLineItemLabel,
    actual: InvoiceLineItemCandidate | None,
    amount_tolerance: Decimal,
) -> list[EvaluationCheck]:
    """Score one expected invoice line item against one actual line item."""

    prefix = f"line_items[{expected.line_number}]"
    if actual is None:
        return [
            failed_check(
                f"{prefix}.present",
                expected="present",
                actual="missing",
            )
        ]

    return [
        check_text(f"{prefix}.description", expected.description, actual.description),
        check_decimal(
            f"{prefix}.quantity",
            expected.quantity,
            actual.quantity,
            tolerance=Decimal("0.0001"),
        ),
        check_decimal(
            f"{prefix}.unit_price",
            expected.unit_price,
            actual.unit_price,
            tolerance=amount_tolerance,
        ),
        check_decimal(
            f"{prefix}.tax_amount",
            expected.tax_amount,
            actual.tax_amount,
            tolerance=amount_tolerance,
        ),
        check_decimal(
            f"{prefix}.line_total",
            expected.line_total,
            actual.line_total,
            tolerance=amount_tolerance,
        ),
    ]


def score_classification_record(
    expected: ExpectedClassificationRecordLabel,
    actual: CategoryClassificationResult,
) -> list[EvaluationCheck]:
    """Score one expected classification record."""

    checks = [
        check_exact(
            f"classification[{expected.source_ref}].category_code",
            expected.category_code,
            actual.category_code,
        ),
        check_exact(
            f"classification[{expected.source_ref}].category_type",
            expected.category_type.value,
            actual.category_type.value,
        ),
        check_exact(
            f"classification[{expected.source_ref}].direction",
            expected.expected_direction,
            actual.proposed_direction,
        ),
        check_confidence_floor(
            f"classification[{expected.source_ref}].confidence",
            expected.confidence_floor,
            actual.confidence,
        ),
    ]
    if expected.rationale_keywords:
        checks.append(
            check_rationale_keywords(
                f"classification[{expected.source_ref}].rationale_keywords",
                expected.rationale_keywords,
                actual,
            )
        )
    return checks


def score_reconciliation_match(
    expected: ExpectedReconciliationMatchLabel,
    actual: ReconciliationCandidate,
) -> list[EvaluationCheck]:
    """Score one expected reconciliation match."""

    return [
        check_exact(
            f"reconciliation[{expected.invoice_number}].transaction_id",
            expected.transaction_id,
            actual.transaction_id,
        ),
        check_exact(
            f"reconciliation[{expected.invoice_number}].transaction_reference",
            expected.transaction_reference,
            metadata_value(actual.metadata, "transaction_reference"),
        ),
        check_absolute_decimal(
            f"reconciliation[{expected.invoice_number}].amount",
            expected.amount,
            metadata_value(actual.metadata, "transaction_amount"),
            tolerance=Decimal("0.01"),
        ),
        check_text(
            f"reconciliation[{expected.invoice_number}].currency",
            expected.currency,
            metadata_value(actual.metadata, "transaction_currency"),
        ),
        check_minimum_int(
            f"reconciliation[{expected.invoice_number}].score",
            expected.min_score,
            actual.score,
        ),
        check_confidence_floor(
            f"reconciliation[{expected.invoice_number}].confidence",
            expected.confidence_floor,
            actual.confidence,
        ),
    ]


def find_reconciliation_candidate(
    *,
    expected_match: ExpectedReconciliationMatchLabel,
    candidates: Sequence[ReconciliationCandidate],
) -> ReconciliationCandidate | None:
    """Find a reconciliation candidate matching an expected invoice/transaction."""

    for candidate in candidates:
        transaction_reference = metadata_value(
            candidate.metadata,
            "transaction_reference",
        )
        if (
            candidate.invoice_number == expected_match.invoice_number
            and candidate.transaction_id == expected_match.transaction_id
        ):
            return candidate
        if (
            candidate.invoice_number == expected_match.invoice_number
            and transaction_reference == expected_match.transaction_reference
        ):
            return candidate
    return None


def report_metric_map(report: FinancialAggregateReport) -> dict[str, object | None]:
    """Return source metrics allowed for grounded insight evaluation."""

    metrics: dict[str, object | None] = {
        "period_start": report.period_start.isoformat()
        if report.period_start is not None
        else None,
        "period_end": report.period_end.isoformat()
        if report.period_end is not None
        else None,
        "currency": report.currency,
        "opening_balance": report.opening_balance,
        "closing_balance": report.closing_balance,
        "expected_closing_balance": report.expected_closing_balance,
        "closing_balance_variance": report.closing_balance_variance,
        "transaction_count": report.transaction_count,
        "inflow_count": report.inflow_count,
        "outflow_count": report.outflow_count,
        "total_inflow": report.total_inflow,
        "total_outflow": report.total_outflow,
        "total_outflow_abs": report.total_outflow_abs,
        "net_change": report.net_change,
        "largest_inflow_ref": report.largest_inflow_ref,
        "largest_inflow_amount": report.largest_inflow_amount,
        "largest_outflow_ref": report.largest_outflow_ref,
        "largest_outflow_amount": report.largest_outflow_amount,
    }
    if report.total_inflow > Decimal("0") and report.largest_inflow_amount is not None:
        metrics["largest_inflow_concentration_percent"] = (
            report.largest_inflow_amount / report.total_inflow * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return metrics


def report_evidence_refs(report: FinancialAggregateReport) -> set[str]:
    """Return evidence references allowed for grounded insight evaluation."""

    evidence_refs = set(report.transaction_evidence_refs)
    evidence_refs.update(report.inflow_evidence_refs)
    evidence_refs.update(report.outflow_evidence_refs)
    for aggregate in report.category_totals:
        evidence_refs.update(aggregate.evidence_refs)
    if report.largest_inflow_ref is not None:
        evidence_refs.add(report.largest_inflow_ref)
    if report.largest_outflow_ref is not None:
        evidence_refs.add(report.largest_outflow_ref)
    return evidence_refs


def review_task_key(
    task: ExpectedReviewTaskLabel | ReviewRoutingActualTask,
) -> str:
    """Return a stable identity key for expected or actual review tasks."""

    return f"{task.task_type.value}:{task.target_ref}:{task.reason_code}"


def check_collection_member(
    name: str,
    *,
    expected_collection: Collection[str],
    actual: str,
    missing_message: str,
) -> EvaluationCheck:
    """Check that a value is a member of an allowed collection."""

    passed = actual in expected_collection
    return EvaluationCheck(
        name=name,
        passed=passed,
        expected="member_of_allowed_set",
        actual=actual if passed else f"unsupported:{actual}",
        message=None if passed else missing_message,
    )


def check_metric_value(
    name: str,
    *,
    expected: object | None,
    actual: object | None,
) -> EvaluationCheck:
    """Check source metric equality with decimal tolerance when possible."""

    expected_decimal = parse_decimal(expected)
    actual_decimal = parse_decimal(actual)
    if expected_decimal is not None or actual_decimal is not None:
        return check_decimal(
            name,
            expected_decimal,
            actual,
            tolerance=Decimal("0.01"),
        )
    return check_text(name, expected, actual)


def check_unmatched_reference_absent(
    *,
    unmatched_ref: str,
    actual_candidates: Sequence[ReconciliationCandidate],
) -> EvaluationCheck:
    """Check that an expected-unmatched transaction was not proposed as matched."""

    matched_candidates = [
        candidate
        for candidate in actual_candidates
        if metadata_value(candidate.metadata, "transaction_reference") == unmatched_ref
    ]
    return EvaluationCheck(
        name=f"reconciliation.unmatched[{unmatched_ref}]",
        passed=not matched_candidates,
        expected="no_candidate",
        actual="candidate_present" if matched_candidates else "no_candidate",
        message=None
        if not matched_candidates
        else "Unexpected candidate was produced.",
    )


def check_text(
    name: str,
    expected: object | None,
    actual: object | None,
) -> EvaluationCheck:
    """Check text equality after trimming whitespace."""

    return check_exact(name, normalize_text(expected), normalize_text(actual))


def check_exact(
    name: str,
    expected: object | None,
    actual: object | None,
) -> EvaluationCheck:
    """Check exact canonical string equality."""

    expected_text = canonical_value(expected)
    actual_text = canonical_value(actual)
    return EvaluationCheck(
        name=name,
        passed=expected_text == actual_text,
        expected=expected_text,
        actual=actual_text,
    )


def check_decimal(
    name: str,
    expected: Decimal | None,
    actual: object | None,
    *,
    tolerance: Decimal,
) -> EvaluationCheck:
    """Check decimal equality within a tolerance."""

    actual_decimal = parse_decimal(actual)
    passed = (
        expected is None
        and actual_decimal is None
        or expected is not None
        and actual_decimal is not None
        and abs(expected - actual_decimal) <= tolerance
    )
    return EvaluationCheck(
        name=name,
        passed=passed,
        expected=str(expected) if expected is not None else None,
        actual=str(actual_decimal) if actual_decimal is not None else None,
        message=None if passed else f"Expected decimal within tolerance {tolerance}.",
    )


def check_absolute_decimal(
    name: str,
    expected: Decimal,
    actual: object | None,
    *,
    tolerance: Decimal,
) -> EvaluationCheck:
    """Check decimal equality using absolute values for signed bank movements."""

    actual_decimal = parse_decimal(actual)
    passed = (
        actual_decimal is not None
        and abs(abs(expected) - abs(actual_decimal)) <= tolerance
    )
    return EvaluationCheck(
        name=name,
        passed=passed,
        expected=str(abs(expected)),
        actual=str(abs(actual_decimal)) if actual_decimal is not None else None,
        message=None if passed else f"Expected absolute decimal within {tolerance}.",
    )


def check_minimum_int(
    name: str,
    expected_minimum: int,
    actual: int,
) -> EvaluationCheck:
    """Check that an integer meets or exceeds a minimum threshold."""

    return EvaluationCheck(
        name=name,
        passed=actual >= expected_minimum,
        expected=f">={expected_minimum}",
        actual=str(actual),
    )


def check_confidence_floor(
    name: str,
    expected_floor: ConfidenceLevel,
    actual: ConfidenceLevel,
) -> EvaluationCheck:
    """Check actual confidence is at least the expected floor."""

    passed = confidence_rank(actual) >= confidence_rank(expected_floor)
    return EvaluationCheck(
        name=name,
        passed=passed,
        expected=f">={expected_floor.value}",
        actual=actual.value,
    )


def check_rationale_keywords(
    name: str,
    expected_keywords: Sequence[str],
    actual: CategoryClassificationResult,
) -> EvaluationCheck:
    """Check expected rationale keywords are present in rationale or match metadata."""

    haystack = " ".join([actual.rationale, *actual.matched_keywords]).lower()
    missing_keywords = [
        keyword for keyword in expected_keywords if keyword.lower() not in haystack
    ]
    return EvaluationCheck(
        name=name,
        passed=not missing_keywords,
        expected=", ".join(expected_keywords),
        actual=", ".join(actual.matched_keywords) or actual.rationale,
        message=(
            None
            if not missing_keywords
            else f"Missing rationale keywords: {', '.join(missing_keywords)}"
        ),
    )


def failed_check(
    name: str,
    *,
    expected: str,
    actual: str,
) -> EvaluationCheck:
    """Build a failed check with canonical expected/actual strings."""

    return EvaluationCheck(
        name=name,
        passed=False,
        expected=expected,
        actual=actual,
    )


def build_score(
    *,
    scorer_name: str,
    checks: Sequence[EvaluationCheck],
    metrics: dict[str, object] | None = None,
) -> EvaluationScore:
    """Build a normalized 0-1 score from field-level checks."""

    check_list = list(checks)
    total_checks = len(check_list)
    passed_checks = sum(1 for check in check_list if check.passed)
    score = passed_checks / total_checks if total_checks else 1.0
    return EvaluationScore(
        scorer_name=scorer_name,
        score=score,
        passed=score == 1.0,
        passed_checks=passed_checks,
        total_checks=total_checks,
        checks=check_list,
        metrics=metrics or {},
    )


def required_csv_value(row: Mapping[str, str], key: str) -> str:
    """Return a required CSV value or raise a deterministic parser error."""

    value = row.get(key)
    if value is None or not value.strip():
        raise ValueError(f"Missing required statement CSV value: {key}")
    return value.strip()


def metadata_value(metadata: Mapping[str, object], key: str) -> str | None:
    """Return a metadata value as a string, if present."""

    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def normalize_text(value: object | None) -> str | None:
    """Normalize text for stable equality checks."""

    if value is None:
        return None
    return " ".join(str(value).strip().split())


def canonical_value(value: object | None) -> str | None:
    """Return a comparable string for check expected/actual values."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def confidence_rank(confidence: ConfidenceLevel) -> int:
    """Return comparable confidence rank."""

    ranks = {
        ConfidenceLevel.UNKNOWN: 0,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.HIGH: 3,
    }
    return ranks[confidence]
