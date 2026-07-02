"""Grounded mock insight generation from deterministic financial aggregates."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.insights.aggregates import FinancialAggregateReport
from app.models.operations import InsightSeverity, InsightType
from app.workflows.contracts import ConfidenceLevel

PERCENT_QUANT = Decimal("0.01")


class GroundedInsight(BaseModel):
    """One mock business insight with traceable source evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "grounded-insight.v1"
    insight_type: InsightType
    severity: InsightSeverity
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    recommendation: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    currency: str | None = None
    estimated_impact_amount: Decimal | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    evidence_refs: list[str] = Field(min_length=1)
    source_metric_keys: list[str] = Field(min_length=1)
    metrics: dict[str, object] = Field(default_factory=dict)


class GroundedInsightPackage(BaseModel):
    """Deterministic insight package ready for dashboard or review surfaces."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "grounded-insight-package.v1"
    generator_name: str = "grounded_mock_insight_generator"
    generator_version: str = "0.1.0"
    insight_count: int = Field(ge=0)
    summary: str
    insights: list[GroundedInsight] = Field(default_factory=list)
    source_report_schema_version: str
    evidence_refs: list[str] = Field(default_factory=list)


class GroundedInsightMockGenerator:
    """Create deterministic, source-grounded business insights."""

    def generate(self, report: FinancialAggregateReport) -> GroundedInsightPackage:
        """Generate a stable set of insights from aggregate metrics."""

        insights = [
            insight
            for insight in [
                build_cashflow_insight(report),
                build_expense_insight(report),
                build_revenue_concentration_insight(report),
            ]
            if insight is not None
        ]
        return GroundedInsightPackage(
            insight_count=len(insights),
            summary=build_package_summary(report=report, insight_count=len(insights)),
            insights=insights,
            source_report_schema_version=report.schema_version,
            evidence_refs=sorted(
                {
                    evidence_ref
                    for insight in insights
                    for evidence_ref in insight.evidence_refs
                }
            ),
        )


def build_cashflow_insight(
    report: FinancialAggregateReport,
) -> GroundedInsight | None:
    """Build a cash movement insight from net cash change."""

    if report.transaction_count == 0 or not report.transaction_evidence_refs:
        return None

    currency = report.currency or "UNKNOWN"
    net_change = report.net_change
    direction = "increased" if net_change >= Decimal("0") else "decreased"
    severity = (
        InsightSeverity.INFO if net_change >= Decimal("0") else InsightSeverity.HIGH
    )
    return GroundedInsight(
        insight_type=InsightType.CASHFLOW,
        severity=severity,
        title=f"Cash {direction} by {currency} {format_money(abs(net_change))}",
        summary=(
            f"During the period, inflows were {currency} "
            f"{format_money(report.total_inflow)} and outflows were {currency} "
            f"{format_money(report.total_outflow_abs)}, resulting in a net "
            f"cash change of {currency} {format_money(net_change)}."
        ),
        recommendation=(
            "Review the transaction-level evidence before publishing this "
            "cashflow insight."
        ),
        period_start=report.period_start.isoformat()
        if report.period_start is not None
        else None,
        period_end=report.period_end.isoformat()
        if report.period_end is not None
        else None,
        currency=report.currency,
        estimated_impact_amount=net_change,
        confidence=ConfidenceLevel.HIGH
        if report.closing_balance_variance == Decimal("0.00")
        else ConfidenceLevel.MEDIUM,
        evidence_refs=report.transaction_evidence_refs,
        source_metric_keys=[
            "total_inflow",
            "total_outflow_abs",
            "net_change",
            "closing_balance_variance",
        ],
        metrics={
            "total_inflow": str(report.total_inflow),
            "total_outflow_abs": str(report.total_outflow_abs),
            "net_change": str(report.net_change),
            "opening_balance": str(report.opening_balance)
            if report.opening_balance is not None
            else None,
            "closing_balance": str(report.closing_balance)
            if report.closing_balance is not None
            else None,
            "closing_balance_variance": str(report.closing_balance_variance)
            if report.closing_balance_variance is not None
            else None,
        },
    )


def build_expense_insight(
    report: FinancialAggregateReport,
) -> GroundedInsight | None:
    """Build an expense summary insight when outflows exist."""

    if report.outflow_count == 0 or not report.outflow_evidence_refs:
        return None

    currency = report.currency or "UNKNOWN"
    severity = (
        InsightSeverity.MEDIUM
        if report.total_outflow_abs > report.total_inflow
        else InsightSeverity.LOW
    )
    largest_outflow = report.largest_outflow_amount or Decimal("0.00")
    return GroundedInsight(
        insight_type=InsightType.EXPENSE,
        severity=severity,
        title=f"Outflows totaled {currency} {format_money(report.total_outflow_abs)}",
        summary=(
            f"{report.outflow_count} outflow transaction(s) totaled {currency} "
            f"{format_money(report.total_outflow_abs)}. The largest outflow was "
            f"{currency} {format_money(largest_outflow)}."
        ),
        recommendation=(
            "Check high-value or recurring expenses for correct classification."
        ),
        period_start=report.period_start.isoformat()
        if report.period_start is not None
        else None,
        period_end=report.period_end.isoformat()
        if report.period_end is not None
        else None,
        currency=report.currency,
        estimated_impact_amount=report.total_outflow_abs,
        confidence=ConfidenceLevel.MEDIUM,
        evidence_refs=report.outflow_evidence_refs,
        source_metric_keys=[
            "outflow_count",
            "total_outflow_abs",
            "largest_outflow_amount",
        ],
        metrics={
            "outflow_count": report.outflow_count,
            "total_outflow_abs": str(report.total_outflow_abs),
            "largest_outflow_amount": str(largest_outflow),
            "largest_outflow_ref": report.largest_outflow_ref,
        },
    )


def build_revenue_concentration_insight(
    report: FinancialAggregateReport,
) -> GroundedInsight | None:
    """Build a simple concentration insight for dominant inflows."""

    if (
        report.total_inflow <= Decimal("0")
        or report.largest_inflow_amount is None
        or report.largest_inflow_ref is None
    ):
        return None

    concentration_ratio = percentage(
        report.largest_inflow_amount / report.total_inflow * Decimal("100")
    )
    if concentration_ratio < Decimal("50.00"):
        return None

    currency = report.currency or "UNKNOWN"
    return GroundedInsight(
        insight_type=InsightType.REVENUE,
        severity=InsightSeverity.MEDIUM,
        title=(
            "Largest inflow contributed "
            f"{format_percentage(concentration_ratio)}% of inflows"
        ),
        summary=(
            f"The largest inflow was {currency} "
            f"{format_money(report.largest_inflow_amount)}, representing "
            f"{format_percentage(concentration_ratio)}% of total inflows."
        ),
        recommendation=(
            "Monitor customer or revenue concentration if this pattern repeats."
        ),
        period_start=report.period_start.isoformat()
        if report.period_start is not None
        else None,
        period_end=report.period_end.isoformat()
        if report.period_end is not None
        else None,
        currency=report.currency,
        estimated_impact_amount=report.largest_inflow_amount,
        confidence=ConfidenceLevel.MEDIUM,
        evidence_refs=[report.largest_inflow_ref],
        source_metric_keys=[
            "largest_inflow_amount",
            "total_inflow",
            "largest_inflow_concentration_percent",
        ],
        metrics={
            "largest_inflow_amount": str(report.largest_inflow_amount),
            "total_inflow": str(report.total_inflow),
            "largest_inflow_concentration_percent": str(concentration_ratio),
            "largest_inflow_ref": report.largest_inflow_ref,
        },
    )


def build_package_summary(
    *,
    report: FinancialAggregateReport,
    insight_count: int,
) -> str:
    """Build a deterministic summary for the generated package."""

    currency = report.currency or "UNKNOWN"
    return (
        f"Generated {insight_count} grounded insight(s) from "
        f"{report.transaction_count} transaction(s); net cash change was "
        f"{currency} {format_money(report.net_change)}."
    )


def format_money(value: Decimal) -> str:
    """Format Decimal money values with two fractional digits."""

    return f"{value.quantize(Decimal('0.01')):,.2f}"


def percentage(value: Decimal) -> Decimal:
    """Normalize percentage values to two decimal places."""

    return value.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def format_percentage(value: Decimal) -> str:
    """Format a normalized percentage without thousands separators."""

    return f"{value.quantize(PERCENT_QUANT):.2f}"
