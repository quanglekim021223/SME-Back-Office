"""Banking API router."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_tenant_context,
    require_permission,
    resolve_tenant_uuid,
)
from app.core.auth import Permission, Principal
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.models.banking import TransactionDirection, TransactionStatus
from app.repositories.banking import TransactionRepository
from app.schemas.banking import BankTransactionListResponse, BankTransactionResponse

router = APIRouter(prefix="/banking", tags=["banking"])


def get_transaction_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransactionRepository:
    """Return the tenant-scoped transaction repository."""

    return TransactionRepository(session)


@router.get("/transactions", response_model=BankTransactionListResponse)
async def list_bank_transactions(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_TENANT)),
    ],
    repository: Annotated[
        TransactionRepository,
        Depends(get_transaction_repository),
    ],
    direction: Annotated[
        TransactionDirection | None,
        Query(description="Filter by inflow, outflow, or unknown direction."),
    ] = None,
    transaction_status: Annotated[
        TransactionStatus | None,
        Query(alias="status", description="Filter by transaction lifecycle status."),
    ] = TransactionStatus.POSTED,
    reconciliation_status: Annotated[
        Literal["matched", "review", "unmatched"] | None,
        Query(description="Filter by invoice reconciliation state."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BankTransactionListResponse:
    """List tenant bank transactions with account and invoice match context."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    transactions, total = await repository.list_for_tenant(
        tenant_id=tenant_id,
        direction_filter=direction.value if direction else None,
        status_filter=transaction_status.value if transaction_status else None,
        reconciliation_status=reconciliation_status,
        limit=limit,
        offset=offset,
    )
    return BankTransactionListResponse(
        items=[
            BankTransactionResponse.from_model(transaction)
            for transaction in transactions
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
