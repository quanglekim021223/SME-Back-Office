"""Invoice API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import (
    get_tenant_context,
    require_permission,
    resolve_tenant_uuid,
)
from app.api.responses import APIError
from app.core.auth import Permission, Principal
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.invoice import (
    InvoiceDetailResponse,
    InvoiceListResponse,
    InvoiceSummaryResponse,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_INVOICES)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description=(
                "Filter by invoice status "
                "(e.g. extracted, superseded, approved)"
            ),
        ),
    ] = None,
    exclude_superseded: Annotated[
        bool,
        Query(description="When true, hide superseded (replaced) invoice versions"),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoiceListResponse:
    """List tenant-scoped invoices, newest version first."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)

    query = select(Invoice).where(Invoice.tenant_id == tenant_id)

    if exclude_superseded:
        query = query.where(Invoice.status != InvoiceStatus.SUPERSEDED.value)

    if status_filter:
        query = query.where(Invoice.status == status_filter)

    count_query = select(func.count()).select_from(query.subquery())
    count_result = await session.execute(count_query)
    total = count_result.scalar_one()

    items_query = query.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(items_query)
    invoices = result.scalars().all()

    return InvoiceListResponse(
        items=[InvoiceSummaryResponse.from_model(inv) for inv in invoices],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice_detail(
    invoice_id: UUID,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_INVOICES)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceDetailResponse:
    """Get detailed information for a single invoice including its line items."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)

    statement = (
        select(Invoice)
        .where(Invoice.tenant_id == tenant_id, Invoice.id == invoice_id)
        .options(selectinload(Invoice.line_items))
    )
    result = await session.execute(statement)
    invoice = result.scalar_one_or_none()

    if invoice is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="invoice_not_found",
            message="Invoice was not found.",
            details={"invoice_id": str(invoice_id)},
        )

    return InvoiceDetailResponse.from_model(invoice)
