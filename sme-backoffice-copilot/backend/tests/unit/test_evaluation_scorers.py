from decimal import Decimal

from app.classification.rules import CategoryClassificationResult
from app.evaluations import (
    ReviewRoutingActualTask,
    load_dataset_fixture_text,
    load_expected_classification_label,
    load_expected_extraction_label,
    load_expected_reconciliation_label,
    load_expected_review_routing_label,
    parse_statement_csv_expected_rows,
    score_classification,
    score_extraction,
    score_insight_groundedness,
    score_reconciliation,
    score_review_routing,
    score_statement_parsing,
)
from app.fixtures import load_statement_parsing_fixture
from app.insights import (
    DeterministicFinancialAggregateService,
    GroundedInsightMockGenerator,
)
from app.models.accounting import CategoryType
from app.models.operations import ReviewTaskPriority, ReviewTaskType
from app.reconciliation.deterministic import (
    ReconciliationCandidate,
    ReconciliationScoreBreakdown,
)
from app.workflows.contracts import ConfidenceLevel
from app.workflows.invoice_extraction import (
    InvoiceExtractionGroups,
    InvoiceLineItemCandidate,
    InvoiceMetadataGroup,
    InvoiceTableGroup,
    InvoiceTotalsGroup,
)


def test_extraction_scorer_returns_perfect_score_for_expected_invoice() -> None:
    expected = load_expected_extraction_label(case_id="invoice_expense_saas_002")
    actual = InvoiceExtractionGroups(
        metadata=InvoiceMetadataGroup(
            invoice_number="BILL-EVAL-002",
            supplier_name="Cloud Tools Example Inc.",
            supplier_tax_id="SYN-TAX-3002",
            customer_name="Demo Advisory Studio LLC",
            customer_tax_id="SYN-TAX-1001",
            issue_date="2026-07-05",
            due_date="2026-07-05",
            currency="USD",
            confidence=ConfidenceLevel.HIGH,
        ),
        table=InvoiceTableGroup(
            line_items=[
                InvoiceLineItemCandidate(
                    line_number=1,
                    description="Team workspace subscription",
                    quantity="5",
                    unit_price="24.00",
                    tax_amount="0.00",
                    line_total="120.00",
                ),
                InvoiceLineItemCandidate(
                    line_number=2,
                    description="Usage overage",
                    quantity="1",
                    unit_price="30.00",
                    tax_amount="0.00",
                    line_total="30.00",
                ),
            ]
        ),
        totals=InvoiceTotalsGroup(
            subtotal_amount="150.00",
            tax_amount="0.00",
            total_amount="150.00",
            currency="USD",
        ),
    )

    score = score_extraction(expected=expected, actual=actual)

    assert score.passed is True
    assert score.score == 1.0
    assert score.passed_checks == score.total_checks


def test_extraction_scorer_reports_field_mismatch() -> None:
    expected = load_expected_extraction_label(case_id="invoice_revenue_services_001")
    actual = InvoiceExtractionGroups(
        metadata=InvoiceMetadataGroup(
            invoice_number="INV-EVAL-001",
            supplier_name="Wrong Supplier LLC",
            customer_name="Example Retail Group",
            issue_date="2026-07-01",
            due_date="2026-07-15",
            currency="USD",
        ),
        table=InvoiceTableGroup(
            line_items=[
                InvoiceLineItemCandidate(
                    line_number=1,
                    description="Monthly bookkeeping advisory",
                    quantity="1",
                    unit_price="1000.00",
                    tax_amount="100.00",
                    line_total="1100.00",
                )
            ]
        ),
        totals=InvoiceTotalsGroup(
            subtotal_amount="1000.00",
            tax_amount="100.00",
            total_amount="1100.00",
            currency="USD",
        ),
    )

    score = score_extraction(expected=expected, actual=actual)

    assert score.passed is False
    assert score.score < 1.0
    assert any(
        check.name == "supplier_name" and not check.passed for check in score.checks
    )


def test_statement_parsing_scorer_scores_csv_rows() -> None:
    csv_text = load_dataset_fixture_text(case_id="statement_operating_july_2026")
    expected_rows = parse_statement_csv_expected_rows(csv_text)

    score = score_statement_parsing(
        expected_rows=expected_rows,
        actual_rows=expected_rows,
    )

    assert score.passed is True
    assert score.score == 1.0
    assert score.metrics["expected_row_count"] == 4


def test_statement_parsing_scorer_reports_amount_mismatch() -> None:
    csv_text = load_dataset_fixture_text(case_id="statement_operating_july_2026")
    expected_rows = parse_statement_csv_expected_rows(csv_text)
    actual_rows = [
        expected_rows[0].model_copy(update={"amount": Decimal("999.00")}),
        *expected_rows[1:],
    ]

    score = score_statement_parsing(
        expected_rows=expected_rows,
        actual_rows=actual_rows,
    )

    assert score.passed is False
    assert any(
        check.name == "statement_row[INV-EVAL-001].amount" and not check.passed
        for check in score.checks
    )


def test_classification_scorer_scores_expected_records() -> None:
    expected = load_expected_classification_label(case_id="invoice_expense_saas_002")
    actual = CategoryClassificationResult(
        category_code="software_subscription",
        category_type=CategoryType.EXPENSE,
        proposed_direction="expense",
        confidence=ConfidenceLevel.HIGH,
        score=96,
        matched_rule_ids=["expense_software_subscription"],
        matched_keywords=["subscription", "usage"],
        rationale="Matched subscription and usage SaaS expense keywords.",
    )

    score = score_classification(
        expected=expected,
        actual_by_source_ref={"invoice:BILL-EVAL-002": actual},
    )

    assert score.passed is True
    assert score.score == 1.0


def test_classification_scorer_reports_wrong_category() -> None:
    expected = load_expected_classification_label(case_id="invoice_expense_saas_002")
    actual = CategoryClassificationResult(
        category_code="rent_expense",
        category_type=CategoryType.EXPENSE,
        proposed_direction="expense",
        confidence=ConfidenceLevel.HIGH,
        score=80,
        matched_rule_ids=["expense_rent"],
        matched_keywords=["rent"],
        rationale="Matched rent expense keywords.",
    )

    score = score_classification(
        expected=expected,
        actual_by_source_ref={"invoice:BILL-EVAL-002": actual},
    )

    assert score.passed is False
    assert any(
        check.name == "classification[invoice:BILL-EVAL-002].category_code"
        and not check.passed
        for check in score.checks
    )


def test_reconciliation_scorer_scores_expected_matches() -> None:
    expected = load_expected_reconciliation_label(
        case_id="statement_operating_july_2026",
    )
    candidates = [
        reconciliation_candidate(
            invoice_number="INV-EVAL-001",
            transaction_id="statement_operating_july_2026:INV-EVAL-001",
            transaction_reference="INV-EVAL-001",
            transaction_amount="1100.00",
        ),
        reconciliation_candidate(
            invoice_number="BILL-EVAL-002",
            transaction_id="statement_operating_july_2026:BILL-EVAL-002",
            transaction_reference="BILL-EVAL-002",
            transaction_amount="-150.00",
        ),
    ]

    score = score_reconciliation(expected=expected, actual_candidates=candidates)

    assert score.passed is True
    assert score.score == 1.0
    assert score.metrics["expected_match_count"] == 2


def test_reconciliation_scorer_reports_unexpected_unmatched_candidate() -> None:
    expected = load_expected_reconciliation_label(
        case_id="statement_operating_july_2026",
    )
    candidates = [
        reconciliation_candidate(
            invoice_number="INV-EVAL-001",
            transaction_id="statement_operating_july_2026:INV-EVAL-001",
            transaction_reference="INV-EVAL-001",
            transaction_amount="1100.00",
        ),
        reconciliation_candidate(
            invoice_number="BILL-EVAL-002",
            transaction_id="statement_operating_july_2026:BILL-EVAL-002",
            transaction_reference="BILL-EVAL-002",
            transaction_amount="-150.00",
        ),
        reconciliation_candidate(
            invoice_number="ADS-JUL-2026",
            transaction_id="statement_operating_july_2026:ADS-JUL-2026",
            transaction_reference="ADS-JUL-2026",
            transaction_amount="-320.00",
        ),
    ]

    score = score_reconciliation(expected=expected, actual_candidates=candidates)

    assert score.passed is False
    assert any(
        check.name == "reconciliation.unmatched[ADS-JUL-2026]" and not check.passed
        for check in score.checks
    )


def test_insight_groundedness_scorer_scores_generated_insights() -> None:
    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        load_statement_parsing_fixture()
    )
    package = GroundedInsightMockGenerator().generate(report)

    score = score_insight_groundedness(report=report, insights=package.insights)

    assert score.passed is True
    assert score.score == 1.0
    assert score.metrics["insight_count"] == 3


def test_insight_groundedness_scorer_reports_unsupported_evidence() -> None:
    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        load_statement_parsing_fixture()
    )
    package = GroundedInsightMockGenerator().generate(report)
    unsupported_insight = package.insights[0].model_copy(
        update={"evidence_refs": ["statement_transaction:unknown"]}
    )

    score = score_insight_groundedness(report=report, insights=[unsupported_insight])

    assert score.passed is False
    assert any(
        "evidence_ref[statement_transaction:unknown]" in check.name and not check.passed
        for check in score.checks
    )


def test_insight_groundedness_scorer_reports_unsupported_metric() -> None:
    report = DeterministicFinancialAggregateService().compute_from_statement_fixture(
        load_statement_parsing_fixture()
    )
    package = GroundedInsightMockGenerator().generate(report)
    insight = package.insights[0]
    unsupported_insight = insight.model_copy(
        update={"metrics": {**insight.metrics, "fabricated_metric": "999.00"}}
    )

    score = score_insight_groundedness(report=report, insights=[unsupported_insight])

    assert score.passed is False
    assert any(
        check.name.endswith(".metric[fabricated_metric].grounded") and not check.passed
        for check in score.checks
    )


def test_review_routing_scorer_scores_expected_review_tasks() -> None:
    expected = load_expected_review_routing_label(
        case_id="statement_operating_july_2026"
    )
    actual_tasks = [
        ReviewRoutingActualTask(
            task_type=ReviewTaskType.RECONCILIATION,
            target_ref="transaction:ADS-JUL-2026",
            reason_code="missing_supporting_document",
            priority=ReviewTaskPriority.NORMAL,
        ),
        ReviewRoutingActualTask(
            task_type=ReviewTaskType.RECONCILIATION,
            target_ref="transaction:RENT-JUL-2026",
            reason_code="missing_supporting_document",
            priority=ReviewTaskPriority.NORMAL,
        ),
    ]

    score = score_review_routing(expected=expected, actual_tasks=actual_tasks)

    assert score.passed is True
    assert score.score == 1.0
    assert score.metrics["actual_task_count"] == 2


def test_review_routing_scorer_reports_missing_expected_task() -> None:
    expected = load_expected_review_routing_label(
        case_id="statement_operating_july_2026"
    )
    actual_tasks = [
        ReviewRoutingActualTask(
            task_type=ReviewTaskType.RECONCILIATION,
            target_ref="transaction:ADS-JUL-2026",
            reason_code="missing_supporting_document",
            priority=ReviewTaskPriority.NORMAL,
        )
    ]

    score = score_review_routing(expected=expected, actual_tasks=actual_tasks)

    assert score.passed is False
    assert any(
        "transaction:RENT-JUL-2026" in check.name and not check.passed
        for check in score.checks
    )


def test_review_routing_scorer_reports_unexpected_task_for_clean_case() -> None:
    expected = load_expected_review_routing_label(
        case_id="invoice_revenue_services_001"
    )
    actual_tasks = [
        ReviewRoutingActualTask(
            task_type=ReviewTaskType.EXTRACTION,
            target_ref="invoice:INV-EVAL-001",
            reason_code="low_confidence",
            priority=ReviewTaskPriority.HIGH,
        )
    ]

    score = score_review_routing(expected=expected, actual_tasks=actual_tasks)

    assert score.passed is False
    assert any(
        check.name == "review_routing.should_create_review_task" and not check.passed
        for check in score.checks
    )


def reconciliation_candidate(
    *,
    invoice_number: str,
    transaction_id: str,
    transaction_reference: str,
    transaction_amount: str,
) -> ReconciliationCandidate:
    return ReconciliationCandidate(
        transaction_id=transaction_id,
        invoice_number=invoice_number,
        score=95,
        confidence=ConfidenceLevel.HIGH,
        score_breakdown=ReconciliationScoreBreakdown(
            amount_score=50,
            date_score=20,
            reference_score=25,
            total_score=95,
            amount_difference=Decimal("0.00"),
            matched_signals=[
                "amount_exact",
                "date_within_due_window",
                "reference_exact",
            ],
        ),
        matched_signals=["amount_exact", "date_within_due_window", "reference_exact"],
        metadata={
            "transaction_reference": transaction_reference,
            "transaction_amount": transaction_amount,
            "transaction_currency": "USD",
        },
    )
