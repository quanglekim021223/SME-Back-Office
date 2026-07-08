"""Invoice API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_tenant_context,
    require_permission,
    resolve_tenant_uuid,
)
from app.api.responses import APIError
from app.core.auth import Permission, Principal
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.repositories.invoices import InvoiceRepository
from app.schemas.invoice import (
    InvoiceDetailResponse,
    InvoiceListResponse,
    InvoiceSummaryResponse,
)
from app.services.audit import AuditService, AuditEvent

router = APIRouter(prefix="/invoices", tags=["invoices"])


def get_invoice_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceRepository:
    """Return the tenant-scoped invoice repository."""

    return InvoiceRepository(session)


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_INVOICES)),
    ],
    repository: Annotated[InvoiceRepository, Depends(get_invoice_repository)],
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

    invoices, total = await repository.list_for_tenant(
        tenant_id=tenant_id,
        status_filter=status_filter,
        exclude_superseded=exclude_superseded,
        limit=limit,
        offset=offset,
    )

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
    repository: Annotated[InvoiceRepository, Depends(get_invoice_repository)],
) -> InvoiceDetailResponse:
    """Get detailed information for a single invoice including its line items."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)

    invoice = await repository.get_for_tenant_with_line_items(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
    )

    if invoice is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="invoice_not_found",
            message="Invoice was not found.",
            details={"invoice_id": str(invoice_id)},
        )

    AuditService().log(
        AuditEvent(
            event="document.accessed",
            tenant_id=str(tenant_id),
            actor_id=principal.user_id,
            resource_type="invoice",
            resource_id=str(invoice_id),
        )
    )

    return InvoiceDetailResponse.from_model(invoice)
