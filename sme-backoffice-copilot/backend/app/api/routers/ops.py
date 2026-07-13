"""Local operations and observability API router."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_tenant_context,
    require_permission,
    resolve_tenant_uuid,
)
from app.core.auth import Permission, Principal
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.observability.metrics import metrics_registry
from app.schemas.dashboard import DashboardFinancialSummaryResponse
from app.services.dashboard_financial_summary import DashboardFinancialSummaryService
from app.services.workflow_jobs import WorkflowJobMetricsService

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/metrics")
async def get_local_metrics(
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_TENANT)),
    ],
) -> dict[str, object]:
    """Return the process-local metrics snapshot for local operations."""

    del principal
    return metrics_registry.snapshot()


@router.get("/workflow-jobs")
async def get_workflow_job_metrics(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_TENANT)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    """Return durable queue metrics aggregated across API and worker processes."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    return await WorkflowJobMetricsService(session).build(tenant_id=tenant_id)


@router.get("/financial-summary", response_model=DashboardFinancialSummaryResponse)
async def get_financial_summary(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_TENANT)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DashboardFinancialSummaryResponse:
    """Return tenant financial aggregates for the local dashboard."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    return await DashboardFinancialSummaryService(session).build_for_tenant(
        tenant_id=tenant_id,
    )
