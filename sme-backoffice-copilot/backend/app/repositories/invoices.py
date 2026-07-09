"""Invoice persistence queries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.accounting import ReconciliationAllocation
from app.models.invoice import Invoice, InvoiceStatus
from app.repositories.base import TenantScopedRepository


class InvoiceRepository(TenantScopedRepository[Invoice]):
    """Repository for tenant-scoped invoice records.

    All single-invoice lookups go through :meth:`get_for_tenant` to enforce
    tenant isolation — a caller who knows a foreign invoice UUID cannot read
    another tenant's invoice data.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Invoice)

    async def list_for_tenant(
        self,
        *,
        tenant_id: UUID,
        status_filter: str | None = None,
        exclude_superseded: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Invoice], int]:
        """Return paginated invoices and total count for one tenant."""

        base_query = select(Invoice).where(Invoice.tenant_id == tenant_id)

        if exclude_superseded:
            base_query = base_query.where(
                Invoice.status != InvoiceStatus.SUPERSEDED.value
            )
        if status_filter is not None:
            base_query = base_query.where(Invoice.status == status_filter)

        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await self.session.execute(count_query)
        total = count_result.scalar_one()

        items_query = (
            base_query.order_by(Invoice.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(items_query)
        return list(result.scalars().all()), total

    async def get_for_tenant_with_line_items(
        self,
        *,
        tenant_id: UUID,
        invoice_id: UUID,
    ) -> Invoice | None:
        """Return one tenant-owned invoice with its line items eagerly loaded."""

        statement = (
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id, Invoice.id == invoice_id)
            .options(
                selectinload(Invoice.classification_proposals),
                selectinload(Invoice.line_items),
                selectinload(Invoice.reconciliation_allocations).selectinload(
                    ReconciliationAllocation.reconciliation
                ),
                selectinload(Invoice.reconciliation_allocations).selectinload(
                    ReconciliationAllocation.transaction
                ),
            )
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
