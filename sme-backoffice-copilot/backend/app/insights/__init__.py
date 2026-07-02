"""Financial aggregate and grounded insight generation utilities."""

from app.insights.aggregates import (
    CategoryAggregate,
    DeterministicFinancialAggregateService,
    FinancialAggregateReport,
    FinancialTransactionInput,
    build_financial_transaction_input,
    compute_category_aggregates,
    normalized_signed_amount,
)
from app.insights.generator import (
    GroundedInsight,
    GroundedInsightMockGenerator,
    GroundedInsightPackage,
)

__all__ = [
    "CategoryAggregate",
    "DeterministicFinancialAggregateService",
    "FinancialAggregateReport",
    "FinancialTransactionInput",
    "GroundedInsight",
    "GroundedInsightMockGenerator",
    "GroundedInsightPackage",
    "build_financial_transaction_input",
    "compute_category_aggregates",
    "normalized_signed_amount",
]
