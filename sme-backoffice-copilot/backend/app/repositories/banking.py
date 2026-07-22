"""Tenant-scoped banking persistence queries."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.selectable import Exists

from app.models.accounting import (
    Reconciliation,
    ReconciliationAllocation,
    ReconciliationAllocationStatus,
    ReconciliationStatus,
)
from app.models.banking import Transaction
from app.repositories.base import TenantScopedRepository

BankTransactionMatchFilter = Literal["matched", "review", "unmatched"]


class TransactionRepository(TenantScopedRepository[Transaction]):
    """Repository for tenant-owned bank transactions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Transaction)

    async def list_for_tenant(
        self,
        *,
        tenant_id: UUID,
        direction_filter: str | None = None,
        status_filter: str | None = None,
        reconciliation_status: BankTransactionMatchFilter | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        """Return filtered transactions and total count for one tenant."""

        base_query = select(Transaction).where(Transaction.tenant_id == tenant_id)
        if direction_filter is not None:
            base_query = base_query.where(
                Transaction.direction == direction_filter
            )
        if status_filter is not None:
            base_query = base_query.where(Transaction.status == status_filter)

        active_allocation = self._has_reconciliation(
            tenant_id=tenant_id,
            approved_only=False,
        )
        approved_allocation = self._has_reconciliation(
            tenant_id=tenant_id,
            approved_only=True,
        )
        if reconciliation_status == "matched":
            base_query = base_query.where(approved_allocation)
        elif reconciliation_status == "review":
            base_query = base_query.where(
                active_allocation,
                ~approved_allocation,
            )
        elif reconciliation_status == "unmatched":
            base_query = base_query.where(~active_allocation)

        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await self.session.execute(count_query)
        total = count_result.scalar_one()

        items_query = (
            base_query.options(
                selectinload(Transaction.bank_account),
                selectinload(Transaction.statement_import),
                selectinload(Transaction.reconciliation_allocations).selectinload(
                    ReconciliationAllocation.reconciliation
                ),
                selectinload(Transaction.reconciliation_allocations).selectinload(
                    ReconciliationAllocation.invoice
                ),
            )
            .order_by(
                Transaction.posted_at.desc().nullslast(),
                Transaction.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(items_query)
        return list(result.scalars().all()), total

    @staticmethod
    def _has_reconciliation(
        *,
        tenant_id: UUID,
        approved_only: bool,
    ) -> Exists:
        allocation_statuses = [
            ReconciliationAllocationStatus.PROPOSED.value,
            ReconciliationAllocationStatus.APPROVED.value,
        ]
        reconciliation_statuses = (
            [ReconciliationStatus.APPROVED.value]
            if approved_only
            else [
                ReconciliationStatus.PROPOSED.value,
                ReconciliationStatus.PENDING_REVIEW.value,
                ReconciliationStatus.APPROVED.value,
            ]
        )
        return exists(
            select(ReconciliationAllocation.id)
            .join(
                Reconciliation,
                Reconciliation.id == ReconciliationAllocation.reconciliation_id,
            )
            .where(
                ReconciliationAllocation.tenant_id == tenant_id,
                ReconciliationAllocation.transaction_id == Transaction.id,
                ReconciliationAllocation.status.in_(allocation_statuses),
                Reconciliation.tenant_id == tenant_id,
                Reconciliation.status.in_(reconciliation_statuses),
            )
        )
