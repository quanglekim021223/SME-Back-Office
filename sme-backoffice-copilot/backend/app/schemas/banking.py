"""Banking API schemas for transaction list views."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.accounting import (
    ReconciliationAllocation,
    ReconciliationAllocationStatus,
    ReconciliationStatus,
)
from app.models.banking import Transaction

BankTransactionMatchStatus = Literal["matched", "review", "unmatched"]


class BankTransactionInvoiceMatchResponse(BaseModel):
    """Compact invoice match attached to a bank transaction."""

    reconciliation_id: UUID
    invoice_id: UUID
    invoice_number: str | None = None
    allocated_amount: Decimal
    currency: str | None = None
    status: str
    confidence: str | None = None

    @classmethod
    def from_model(
        cls,
        allocation: ReconciliationAllocation,
    ) -> BankTransactionInvoiceMatchResponse:
        """Build a match response from an eagerly loaded allocation."""

        assert allocation.invoice_id is not None
        reconciliation = allocation.reconciliation
        invoice = allocation.invoice
        return cls(
            reconciliation_id=allocation.reconciliation_id,
            invoice_id=allocation.invoice_id,
            invoice_number=invoice.invoice_number if invoice else None,
            allocated_amount=allocation.allocated_amount,
            currency=allocation.currency,
            status=reconciliation.status,
            confidence=allocation.confidence or reconciliation.confidence,
        )


class BankTransactionResponse(BaseModel):
    """Transaction list row with account and reconciliation context."""

    id: UUID
    tenant_id: UUID
    bank_account_id: UUID
    bank_account_name: str | None = None
    institution_name: str
    masked_account_number: str | None = None
    statement_import_id: UUID | None = None
    source_filename: str | None = None
    status: str
    direction: str
    posted_at: date | None = None
    value_at: date | None = None
    description: str | None = None
    counterparty_name: str | None = None
    reference: str | None = None
    amount: Decimal
    currency: str | None = None
    running_balance: Decimal | None = None
    confidence: str | None = None
    reconciliation_status: BankTransactionMatchStatus
    invoice_matches: list[BankTransactionInvoiceMatchResponse] = Field(
        default_factory=list
    )
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, transaction: Transaction) -> BankTransactionResponse:
        """Build a response from a transaction and its loaded relationships."""

        active_allocations = [
            allocation
            for allocation in transaction.reconciliation_allocations
            if allocation.invoice_id is not None
            and allocation.status
            not in {
                ReconciliationAllocationStatus.REJECTED.value,
                ReconciliationAllocationStatus.SUPERSEDED.value,
            }
            and allocation.reconciliation.status
            not in {
                ReconciliationStatus.REJECTED.value,
                ReconciliationStatus.SUPERSEDED.value,
            }
        ]
        is_matched = any(
            allocation.reconciliation.status == ReconciliationStatus.APPROVED.value
            for allocation in active_allocations
        )
        match_status: BankTransactionMatchStatus = (
            "matched"
            if is_matched
            else "review"
            if active_allocations
            else "unmatched"
        )
        account = transaction.bank_account
        statement_import = transaction.statement_import

        return cls(
            id=transaction.id,
            tenant_id=transaction.tenant_id,
            bank_account_id=transaction.bank_account_id,
            bank_account_name=account.account_name,
            institution_name=account.institution_name,
            masked_account_number=account.masked_account_number,
            statement_import_id=transaction.statement_import_id,
            source_filename=(
                statement_import.source_filename if statement_import else None
            ),
            status=transaction.status,
            direction=transaction.direction,
            posted_at=transaction.posted_at,
            value_at=transaction.value_at,
            description=(
                transaction.normalized_description or transaction.raw_description
            ),
            counterparty_name=transaction.counterparty_name,
            reference=transaction.reference,
            amount=transaction.amount,
            currency=transaction.currency,
            running_balance=transaction.running_balance,
            confidence=transaction.confidence,
            reconciliation_status=match_status,
            invoice_matches=[
                BankTransactionInvoiceMatchResponse.from_model(allocation)
                for allocation in sorted(
                    active_allocations,
                    key=lambda item: item.created_at,
                    reverse=True,
                )
            ],
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )


class BankTransactionListResponse(BaseModel):
    """Paginated bank transaction list response."""

    items: list[BankTransactionResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
