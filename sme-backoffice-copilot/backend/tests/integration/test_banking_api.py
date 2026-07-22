"""Bank transaction list API tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.banking import get_transaction_repository
from app.models.banking import (
    BankAccount,
    StatementImport,
    Transaction,
    TransactionDirection,
    TransactionStatus,
)
from app.models.base import utc_now


class FakeTransactionRepository:
    def __init__(self, transactions: list[Transaction]) -> None:
        self.transactions = transactions
        self.calls: list[dict[str, object]] = []

    async def list_for_tenant(self, **kwargs) -> tuple[list[Transaction], int]:
        self.calls.append(kwargs)
        tenant_transactions = [
            transaction
            for transaction in self.transactions
            if transaction.tenant_id == kwargs["tenant_id"]
        ]
        return tenant_transactions, len(tenant_transactions)


def auth_headers(tenant_id: UUID) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-User-ID": str(uuid4()),
        "X-User-Role": "member",
    }


def build_transaction(*, tenant_id: UUID) -> Transaction:
    now = utc_now()
    account = BankAccount(
        id=uuid4(),
        tenant_id=tenant_id,
        institution_name="Example Bank",
        account_name="Operating account",
        account_type="checking",
        currency="USD",
        masked_account_number="****4821",
        created_at=now,
        updated_at=now,
    )
    statement_import = StatementImport(
        id=uuid4(),
        tenant_id=tenant_id,
        bank_account_id=account.id,
        source_filename="bank_statement_4821.csv",
        status="parsed",
        created_at=now,
        updated_at=now,
    )
    return Transaction(
        id=uuid4(),
        tenant_id=tenant_id,
        bank_account_id=account.id,
        statement_import_id=statement_import.id,
        status=TransactionStatus.POSTED.value,
        direction=TransactionDirection.INFLOW.value,
        posted_at=date(2026, 7, 14),
        raw_description="ACH PAYMENT EAST REPAIR INC US-001",
        amount=Decimal("154.06"),
        currency="USD",
        content_hash=str(uuid4()),
        bank_account=account,
        statement_import=statement_import,
        reconciliation_allocations=[],
        created_at=now,
        updated_at=now,
    )


def test_list_bank_transactions_returns_tenant_scoped_rows(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    transaction = build_transaction(tenant_id=tenant_id)
    repository = FakeTransactionRepository(
        [transaction, build_transaction(tenant_id=uuid4())]
    )
    app.dependency_overrides[get_transaction_repository] = lambda: repository

    response = client.get(
        "/api/v1/banking/transactions"
        "?direction=inflow&status=posted&reconciliation_status=unmatched",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(transaction.id)
    assert payload["items"][0]["institution_name"] == "Example Bank"
    assert payload["items"][0]["source_filename"] == "bank_statement_4821.csv"
    assert payload["items"][0]["reconciliation_status"] == "unmatched"
    assert repository.calls[0]["direction_filter"] == "inflow"
    assert repository.calls[0]["status_filter"] == "posted"
    assert repository.calls[0]["reconciliation_status"] == "unmatched"
