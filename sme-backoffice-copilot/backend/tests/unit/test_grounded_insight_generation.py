from decimal import Decimal

from app.fixtures import load_statement_parsing_fixture
from app.insights import (
    DeterministicFinancialAggregateService,
    GroundedInsightMockGenerator,
)
from app.models.operations import InsightSeverity, InsightType
from app.workflows import ConfidenceLevel


def build_fixture_report():
    fixture = load_statement_parsing_fixture()
    return DeterministicFinancialAggregateService().compute_from_statement_fixture(
        fixture
    )


def test_grounded_insight_generator_creates_fixture_insights() -> None:
    report = build_fixture_report()

    package = GroundedInsightMockGenerator().generate(report)

    assert package.generator_name == "grounded_mock_insight_generator"
    assert package.source_report_schema_version == report.schema_version
    assert package.insight_count == 3
    assert package.summary == (
        "Generated 3 grounded insight(s) from 3 transaction(s); "
        "net cash change was USD 215.00."
    )
    assert {insight.insight_type for insight in package.insights} == {
        InsightType.CASHFLOW,
        InsightType.EXPENSE,
        InsightType.REVENUE,
    }


def test_cashflow_insight_is_grounded_in_transaction_evidence() -> None:
    report = build_fixture_report()

    package = GroundedInsightMockGenerator().generate(report)
    cashflow_insight = next(
        insight
        for insight in package.insights
        if insight.insight_type == InsightType.CASHFLOW
    )

    assert cashflow_insight.title == "Cash increased by USD 215.00"
    assert cashflow_insight.severity == InsightSeverity.INFO
    assert cashflow_insight.confidence == ConfidenceLevel.HIGH
    assert cashflow_insight.estimated_impact_amount == Decimal("215.00")
    assert cashflow_insight.evidence_refs == report.transaction_evidence_refs
    assert cashflow_insight.source_metric_keys == [
        "total_inflow",
        "total_outflow_abs",
        "net_change",
        "closing_balance_variance",
    ]
    assert cashflow_insight.metrics["net_change"] == "215.00"


def test_expense_insight_uses_outflow_evidence_only() -> None:
    report = build_fixture_report()

    package = GroundedInsightMockGenerator().generate(report)
    expense_insight = next(
        insight
        for insight in package.insights
        if insight.insight_type == InsightType.EXPENSE
    )

    assert expense_insight.title == "Outflows totaled USD 45.00"
    assert expense_insight.severity == InsightSeverity.LOW
    assert expense_insight.evidence_refs == ["statement_transaction:demo-bank-txn-002"]
    assert expense_insight.metrics["largest_outflow_ref"] == (
        "statement_transaction:demo-bank-txn-002"
    )


def test_revenue_concentration_insight_uses_largest_inflow_evidence() -> None:
    report = build_fixture_report()

    package = GroundedInsightMockGenerator().generate(report)
    revenue_insight = next(
        insight
        for insight in package.insights
        if insight.insight_type == InsightType.REVENUE
    )

    assert revenue_insight.title == ("Largest inflow contributed 57.69% of inflows")
    assert revenue_insight.evidence_refs == ["statement_transaction:demo-bank-txn-003"]
    assert revenue_insight.metrics["largest_inflow_concentration_percent"] == "57.69"
    assert revenue_insight.estimated_impact_amount == Decimal("150.00")


def test_every_grounded_insight_has_evidence_and_metric_keys() -> None:
    report = build_fixture_report()

    package = GroundedInsightMockGenerator().generate(report)

    assert package.evidence_refs == sorted(set(report.transaction_evidence_refs))
    for insight in package.insights:
        assert insight.evidence_refs
        assert insight.source_metric_keys
        assert insight.metrics
