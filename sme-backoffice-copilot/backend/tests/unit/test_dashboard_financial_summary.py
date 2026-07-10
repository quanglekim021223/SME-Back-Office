"""Tests for dashboard financial summary aggregates."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.models.banking import Transaction, TransactionDirection, TransactionStatus
from app.services.dashboard_financial_summary import build_financial_summary


def test_dashboard_summary_computes_inflow_outflow_and_cash_position() -> None:
    tenant_id = uuid4()
    account_id = uuid4()
    transactions = [
        build_transaction(
            tenant_id=tenant_id,
            account_id=account_id,
            posted_at=date(2026, 7, 1),
            amount=Decimal("500.00"),
            direction=TransactionDirection.INFLOW,
            balance=Decimal("1500.00"),
        ),
        build_transaction(
            tenant_id=tenant_id,
            account_id=account_id,
            posted_at=date(2026, 7, 2),
            amount=Decimal("-125.25"),
            direction=TransactionDirection.OUTFLOW,
            balance=Decimal("1374.75"),
        ),
        build_transaction(
            tenant_id=tenant_id,
            account_id=account_id,
            posted_at=date(2026, 7, 3),
            amount=Decimal("75.00"),
            direction=TransactionDirection.INFLOW,
            balance=Decimal("1449.75"),
        ),
    ]

    summary = build_financial_summary(transactions=transactions)

    assert summary.inflow.available is True
    assert summary.inflow.amount == Decimal("575.00")
    assert summary.inflow.transaction_count == 2
    assert summary.outflow.available is True
    assert summary.outflow.amount == Decimal("125.25")
    assert summary.outflow.transaction_count == 1
    assert summary.cash_position.available is True
    assert summary.cash_position.amount == Decimal("1449.75")
    assert summary.cash_position.account_count == 1
    assert summary.cash_position.source == "Latest transaction running balance"


def test_dashboard_summary_does_not_fake_cash_position_without_balance() -> None:
    tenant_id = uuid4()
    account_id = uuid4()
    transactions = [
        build_transaction(
            tenant_id=tenant_id,
            account_id=account_id,
            posted_at=date(2026, 7, 1),
            amount=Decimal("500.00"),
            direction=TransactionDirection.INFLOW,
            balance=None,
        )
    ]

    summary = build_financial_summary(transactions=transactions)

    assert summary.cash_position.available is False
    assert summary.cash_position.amount is None
    assert summary.cash_position.source == "No statement balance imported yet"
    assert summary.inflow.available is True
    assert summary.inflow.amount == Decimal("500.00")


def build_transaction(
    *,
    tenant_id,
    account_id,
    posted_at: date,
    amount: Decimal,
    direction: TransactionDirection,
    balance: Decimal | None,
) -> Transaction:
    return Transaction(
        id=uuid4(),
        tenant_id=tenant_id,
        bank_account_id=account_id,
        status=TransactionStatus.POSTED.value,
        direction=direction.value,
        posted_at=posted_at,
        amount=amount,
        currency="USD",
        running_balance=balance,
        content_hash=str(uuid4()),
        created_at=datetime(2026, 7, posted_at.day, 9, 0, 0),
    )
