"""Deterministic financial aggregate service for parsed bank statement data."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.classification import classify_statement_transaction
from app.fixtures.loader import StatementParsingFixture, StatementTransactionFixture
from app.models.accounting import CategoryType
from app.models.banking import TransactionDirection

MONEY_QUANT = Decimal("0.01")


class FinancialTransactionInput(BaseModel):
    """Normalized transaction input for deterministic financial aggregates."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1)
    posted_at: date | None = None
    amount: Decimal
    signed_amount: Decimal
    currency: str | None = None
    direction: TransactionDirection = TransactionDirection.UNKNOWN
    category_code: str | None = None
    category_type: CategoryType | None = None
    description: str | None = None
    counterparty_name: str | None = None
    evidence_ref: str = Field(min_length=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class CategoryAggregate(BaseModel):
    """Aggregate totals for one category code."""

    model_config = ConfigDict(extra="forbid")

    category_code: str = Field(min_length=1)
    category_type: CategoryType | None = None
    transaction_count: int = Field(ge=0)
    total_amount: Decimal
    absolute_amount: Decimal
    evidence_refs: list[str] = Field(default_factory=list)


class FinancialAggregateReport(BaseModel):
    """Deterministic cashflow and category summary for a statement period."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "financial-aggregate-report.v1"
    period_start: date | None = None
    period_end: date | None = None
    currency: str | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    expected_closing_balance: Decimal | None = None
    closing_balance_variance: Decimal | None = None
    transaction_count: int = Field(ge=0)
    inflow_count: int = Field(ge=0)
    outflow_count: int = Field(ge=0)
    total_inflow: Decimal
    total_outflow: Decimal
    total_outflow_abs: Decimal
    net_change: Decimal
    category_totals: list[CategoryAggregate] = Field(default_factory=list)
    transaction_evidence_refs: list[str] = Field(default_factory=list)
    inflow_evidence_refs: list[str] = Field(default_factory=list)
    outflow_evidence_refs: list[str] = Field(default_factory=list)
    largest_inflow_ref: str | None = None
    largest_inflow_amount: Decimal | None = None
    largest_outflow_ref: str | None = None
    largest_outflow_amount: Decimal | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DeterministicFinancialAggregateService:
    """Compute repeatable financial metrics without LLM dependencies."""

    def compute_from_statement_fixture(
        self,
        fixture: StatementParsingFixture,
    ) -> FinancialAggregateReport:
        """Compute aggregates from a validated statement parsing fixture."""

        transactions = [
            build_financial_transaction_input(transaction)
            for transaction in fixture.transactions
        ]
        return self.compute(
            transactions=transactions,
            period_start=fixture.statement_import.statement_start_date,
            period_end=fixture.statement_import.statement_end_date,
            currency=fixture.statement_import.currency or fixture.bank_account.currency,
            opening_balance=fixture.statement_import.opening_balance,
            closing_balance=fixture.statement_import.closing_balance,
            metadata={
                "source": "statement_parsing_fixture",
                "fixture_name": fixture.fixture_name,
                "bank_institution_name": fixture.bank_account.institution_name,
                "bank_account_name": fixture.bank_account.account_name,
                "source_filename": fixture.statement_import.source_filename,
            },
        )

    def compute(
        self,
        *,
        transactions: list[FinancialTransactionInput],
        period_start: date | None = None,
        period_end: date | None = None,
        currency: str | None = None,
        opening_balance: Decimal | None = None,
        closing_balance: Decimal | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FinancialAggregateReport:
        """Compute cash movement, balance variance, and category totals."""

        sorted_transactions = sorted(
            transactions,
            key=lambda transaction: (
                transaction.posted_at or date.min,
                transaction.transaction_id,
            ),
        )
        inflows = [
            transaction
            for transaction in sorted_transactions
            if transaction.signed_amount > Decimal("0")
        ]
        outflows = [
            transaction
            for transaction in sorted_transactions
            if transaction.signed_amount < Decimal("0")
        ]
        total_inflow = money_sum(transaction.signed_amount for transaction in inflows)
        total_outflow = money_sum(transaction.signed_amount for transaction in outflows)
        net_change = money_sum(
            transaction.signed_amount for transaction in sorted_transactions
        )
        expected_closing_balance = (
            money(opening_balance + net_change) if opening_balance is not None else None
        )
        closing_balance_variance = (
            money(closing_balance - expected_closing_balance)
            if closing_balance is not None and expected_closing_balance is not None
            else None
        )
        largest_inflow = max(
            inflows,
            key=lambda transaction: transaction.signed_amount,
            default=None,
        )
        largest_outflow = min(
            outflows,
            key=lambda transaction: transaction.signed_amount,
            default=None,
        )

        return FinancialAggregateReport(
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            opening_balance=money_or_none(opening_balance),
            closing_balance=money_or_none(closing_balance),
            expected_closing_balance=expected_closing_balance,
            closing_balance_variance=closing_balance_variance,
            transaction_count=len(sorted_transactions),
            inflow_count=len(inflows),
            outflow_count=len(outflows),
            total_inflow=total_inflow,
            total_outflow=total_outflow,
            total_outflow_abs=abs(total_outflow),
            net_change=net_change,
            category_totals=compute_category_aggregates(sorted_transactions),
            transaction_evidence_refs=[
                transaction.evidence_ref for transaction in sorted_transactions
            ],
            inflow_evidence_refs=[transaction.evidence_ref for transaction in inflows],
            outflow_evidence_refs=[
                transaction.evidence_ref for transaction in outflows
            ],
            largest_inflow_ref=largest_inflow.evidence_ref
            if largest_inflow is not None
            else None,
            largest_inflow_amount=largest_inflow.signed_amount
            if largest_inflow is not None
            else None,
            largest_outflow_ref=largest_outflow.evidence_ref
            if largest_outflow is not None
            else None,
            largest_outflow_amount=abs(largest_outflow.signed_amount)
            if largest_outflow is not None
            else None,
            metadata=metadata or {},
        )


def build_financial_transaction_input(
    transaction: StatementTransactionFixture,
) -> FinancialTransactionInput:
    """Build aggregate input from a parsed statement transaction fixture."""

    classification = classify_statement_transaction(transaction)
    transaction_id = transaction.external_transaction_id or transaction.content_hash
    description = " ".join(
        part
        for part in [
            transaction.raw_description,
            transaction.normalized_description,
            transaction.counterparty_name,
            transaction.reference,
        ]
        if part
    )
    return FinancialTransactionInput(
        transaction_id=transaction_id,
        posted_at=transaction.posted_at,
        amount=money(transaction.amount),
        signed_amount=normalized_signed_amount(
            amount=transaction.amount,
            direction=transaction.direction,
        ),
        currency=transaction.currency,
        direction=transaction.direction,
        category_code=classification.category_code,
        category_type=classification.category_type,
        description=description or None,
        counterparty_name=transaction.counterparty_name,
        evidence_ref=f"statement_transaction:{transaction_id}",
        metadata={
            "content_hash": transaction.content_hash,
            "classification_confidence": classification.confidence.value,
            "matched_rule_ids": classification.matched_rule_ids,
        },
    )


def normalized_signed_amount(
    *,
    amount: Decimal,
    direction: TransactionDirection,
) -> Decimal:
    """Return a stable signed amount using transaction direction when available."""

    if direction == TransactionDirection.INFLOW:
        return money(abs(amount))
    if direction == TransactionDirection.OUTFLOW:
        return money(-abs(amount))
    return money(amount)


def compute_category_aggregates(
    transactions: list[FinancialTransactionInput],
) -> list[CategoryAggregate]:
    """Compute deterministic totals grouped by category code."""

    grouped: dict[str, list[FinancialTransactionInput]] = {}
    for transaction in transactions:
        category_code = transaction.category_code or "uncategorized"
        grouped.setdefault(category_code, []).append(transaction)

    aggregates: list[CategoryAggregate] = []
    for category_code, category_transactions in grouped.items():
        total_amount = money_sum(
            transaction.signed_amount for transaction in category_transactions
        )
        category_type = next(
            (
                transaction.category_type
                for transaction in category_transactions
                if transaction.category_type is not None
            ),
            None,
        )
        aggregates.append(
            CategoryAggregate(
                category_code=category_code,
                category_type=category_type,
                transaction_count=len(category_transactions),
                total_amount=total_amount,
                absolute_amount=abs(total_amount),
                evidence_refs=[
                    transaction.evidence_ref for transaction in category_transactions
                ],
            )
        )
    return sorted(
        aggregates,
        key=lambda aggregate: (-aggregate.absolute_amount, aggregate.category_code),
    )


def money(value: Decimal) -> Decimal:
    """Normalize money values to two decimal places."""

    return value.quantize(MONEY_QUANT)


def money_or_none(value: Decimal | None) -> Decimal | None:
    """Normalize optional money values."""

    return money(value) if value is not None else None


def money_sum(values: Iterable[Decimal]) -> Decimal:
    """Return a normalized Decimal sum."""

    total = Decimal("0.00")
    for value in values:
        if isinstance(value, Decimal):
            total += value
    return money(total)
