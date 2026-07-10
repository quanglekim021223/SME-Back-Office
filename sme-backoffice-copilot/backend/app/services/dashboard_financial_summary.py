"""Tenant financial aggregates for the local dashboard."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import (
    StatementImport,
    StatementImportStatus,
    Transaction,
    TransactionDirection,
    TransactionStatus,
)
from app.schemas.dashboard import (
    DashboardFinancialSummaryResponse,
    FinancialMetricResponse,
)

UNKNOWN_CURRENCY = "UNK"
ZERO = Decimal("0.00")


class DashboardFinancialSummaryService:
    """Build dashboard cashflow metrics from parsed bank transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_for_tenant(
        self,
        *,
        tenant_id: UUID,
    ) -> DashboardFinancialSummaryResponse:
        """Return tenant-scoped financial dashboard aggregates."""

        transaction_result = await self.session.execute(
            select(Transaction)
            .where(
                Transaction.tenant_id == tenant_id,
                Transaction.status == TransactionStatus.POSTED.value,
            )
            .order_by(Transaction.posted_at.asc(), Transaction.created_at.asc())
        )
        transactions = list(transaction_result.scalars().all())

        statement_result = await self.session.execute(
            select(StatementImport).where(
                StatementImport.tenant_id == tenant_id,
                StatementImport.status == StatementImportStatus.PARSED.value,
                StatementImport.closing_balance.is_not(None),
            )
        )
        statements = list(statement_result.scalars().all())

        return build_financial_summary(
            transactions=transactions,
            statement_imports=statements,
        )


def build_financial_summary(
    *,
    transactions: list[Transaction],
    statement_imports: list[StatementImport] | None = None,
) -> DashboardFinancialSummaryResponse:
    """Build a dashboard summary from loaded transaction records."""

    statement_imports = statement_imports or []
    posted_transactions = [
        transaction
        for transaction in transactions
        if transaction.status == TransactionStatus.POSTED.value
    ]
    dated_transactions = [
        transaction.posted_at
        for transaction in posted_transactions
        if transaction.posted_at is not None
    ]
    period_start = min(dated_transactions) if dated_transactions else None
    period_end = max(dated_transactions) if dated_transactions else None

    inflows = [
        transaction for transaction in posted_transactions if is_inflow(transaction)
    ]
    outflows = [
        transaction for transaction in posted_transactions if is_outflow(transaction)
    ]

    return DashboardFinancialSummaryResponse(
        cash_position=summarize_cash_position(
            posted_transactions,
            statement_imports,
        ),
        inflow=summarize_amounts(
            rows=[
                (
                    normalized_currency(transaction.currency),
                    abs(transaction.amount),
                )
                for transaction in inflows
            ],
            transaction_count=len(inflows),
            period_start=period_start,
            period_end=period_end,
            source=(
                "Parsed bank transactions"
                if inflows
                else "No inflow transactions imported yet"
            ),
        ),
        outflow=summarize_amounts(
            rows=[
                (
                    normalized_currency(transaction.currency),
                    abs(transaction.amount),
                )
                for transaction in outflows
            ],
            transaction_count=len(outflows),
            period_start=period_start,
            period_end=period_end,
            source=(
                "Parsed bank transactions"
                if outflows
                else "No outflow transactions imported yet"
            ),
        ),
        generated_at=datetime.now(UTC),
    )


def summarize_cash_position(
    transactions: list[Transaction],
    statement_imports: list[StatementImport],
) -> FinancialMetricResponse:
    """Return latest known balance across accounts when statement data has it."""

    latest_transaction_balance_by_account: dict[UUID, Transaction] = {}
    for transaction in transactions:
        if transaction.running_balance is None:
            continue
        current = latest_transaction_balance_by_account.get(transaction.bank_account_id)
        if current is None or transaction_sort_key(transaction) > transaction_sort_key(
            current
        ):
            latest_transaction_balance_by_account[transaction.bank_account_id] = (
                transaction
            )

    if latest_transaction_balance_by_account:
        balances = [
            (normalized_currency(transaction.currency), transaction.running_balance)
            for transaction in latest_transaction_balance_by_account.values()
            if transaction.running_balance is not None
        ]
        return summarize_amounts(
            rows=balances,
            transaction_count=len(balances),
            account_count=len(latest_transaction_balance_by_account),
            period_start=None,
            period_end=max(
                (
                    transaction.posted_at
                    for transaction in latest_transaction_balance_by_account.values()
                    if transaction.posted_at is not None
                ),
                default=None,
            ),
            source="Latest transaction running balance",
        )

    latest_statement_by_account: dict[UUID, StatementImport] = {}
    for statement in statement_imports:
        if statement.closing_balance is None:
            continue
        current = latest_statement_by_account.get(statement.bank_account_id)
        if current is None or statement_sort_key(statement) > statement_sort_key(
            current
        ):
            latest_statement_by_account[statement.bank_account_id] = statement

    if latest_statement_by_account:
        balances = [
            (normalized_currency(statement.currency), statement.closing_balance)
            for statement in latest_statement_by_account.values()
            if statement.closing_balance is not None
        ]
        return summarize_amounts(
            rows=balances,
            transaction_count=0,
            account_count=len(latest_statement_by_account),
            period_start=None,
            period_end=max(
                (
                    statement.statement_end_date
                    for statement in latest_statement_by_account.values()
                    if statement.statement_end_date is not None
                ),
                default=None,
            ),
            source="Latest statement closing balance",
        )

    return FinancialMetricResponse(
        available=False,
        source="No statement balance imported yet",
    )


def summarize_amounts(
    *,
    rows: list[tuple[str, Decimal]],
    transaction_count: int,
    source: str,
    account_count: int = 0,
    period_start: date | None = None,
    period_end: date | None = None,
) -> FinancialMetricResponse:
    """Summarize currency-aware amounts without mixing currencies."""

    by_currency: dict[str, Decimal] = {}
    for currency, amount in rows:
        by_currency[currency] = by_currency.get(currency, ZERO) + amount

    if not by_currency:
        return FinancialMetricResponse(
            available=False,
            transaction_count=transaction_count,
            account_count=account_count,
            period_start=period_start,
            period_end=period_end,
            source=source,
        )

    currency: str | None = None
    amount: Decimal | None = None
    if len(by_currency) == 1:
        currency, amount = next(iter(by_currency.items()))

    return FinancialMetricResponse(
        available=True,
        amount=amount,
        currency=currency,
        by_currency=by_currency,
        transaction_count=transaction_count,
        account_count=account_count,
        period_start=period_start,
        period_end=period_end,
        source=source if amount is not None else "Multiple currencies imported",
    )


def is_inflow(transaction: Transaction) -> bool:
    """Return whether a transaction should count as dashboard inflow."""

    return (
        transaction.direction == TransactionDirection.INFLOW.value
        or transaction.amount > ZERO
    )


def is_outflow(transaction: Transaction) -> bool:
    """Return whether a transaction should count as dashboard outflow."""

    return (
        transaction.direction == TransactionDirection.OUTFLOW.value
        or transaction.amount < ZERO
    )


def normalized_currency(currency: str | None) -> str:
    """Return a stable currency bucket label."""

    return currency or UNKNOWN_CURRENCY


def transaction_sort_key(transaction: Transaction) -> tuple[date, float]:
    """Return a stable recency key for transaction balances."""

    return (
        transaction.posted_at or transaction.value_at or date.min,
        timestamp_or_zero(transaction.created_at),
    )


def statement_sort_key(statement: StatementImport) -> tuple[date, float]:
    """Return a stable recency key for statement balances."""

    return (
        statement.statement_end_date or date.min,
        timestamp_or_zero(statement.created_at),
    )


def timestamp_or_zero(value: datetime | None) -> float:
    """Return a comparable timestamp for optional ORM timestamps."""

    return value.timestamp() if value is not None else 0.0
