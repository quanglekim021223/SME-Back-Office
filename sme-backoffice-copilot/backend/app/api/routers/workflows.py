"""Read-only workflow execution API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
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
from app.repositories.workflows import WorkflowRuntimeRepository
from app.schemas.workflow import WorkflowRunStatusResponse

router = APIRouter(prefix="/workflow-runs", tags=["workflows"])


@router.get("/{workflow_run_id}", response_model=WorkflowRunStatusResponse)
async def get_workflow_run_status(
    workflow_run_id: UUID,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_INVOICES)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowRunStatusResponse:
    """Return a workflow run without exposing cross-tenant execution state."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    workflow_run = await WorkflowRuntimeRepository(session).get_for_tenant(
        tenant_id=tenant_id,
        object_id=workflow_run_id,
    )
    if workflow_run is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_run_not_found",
            message="Workflow run was not found.",
            details={"workflow_run_id": str(workflow_run_id)},
        )

    return WorkflowRunStatusResponse.from_model(workflow_run)
