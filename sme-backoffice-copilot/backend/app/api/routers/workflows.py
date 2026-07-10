"""Read-only workflow execution API."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
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
from app.jobs import JobStatus, WorkflowJobQueue
from app.repositories.workflows import WorkflowRuntimeRepository
from app.schemas.workflow import WorkflowRunStatusResponse
from app.workflows.contracts import WorkflowState, WorkflowStateStatus
from app.workflows.runtime import WorkflowRuntimeService

router = APIRouter(prefix="/workflow-runs", tags=["workflows"])


@router.get("/{workflow_run_id}", response_model=WorkflowRunStatusResponse)
async def get_workflow_run_status(
    workflow_run_id: UUID,
    request: Request,
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

    queue = cast(WorkflowJobQueue, request.app.state.workflow_job_queue)
    return WorkflowRunStatusResponse.from_model(
        workflow_run,
        live_progress=await queue.get_progress(workflow_run.id),
    )


@router.post("/{workflow_run_id}/cancel", response_model=WorkflowRunStatusResponse)
async def cancel_workflow_run(
    workflow_run_id: UUID,
    request: Request,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.WRITE_DOCUMENTS)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowRunStatusResponse:
    """Cancel a workflow only while its queued job has not started."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    repository = WorkflowRuntimeRepository(session)
    workflow_run = await repository.get_for_tenant(
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
    if workflow_run.status != WorkflowStateStatus.QUEUED.value:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="workflow_not_cancellable",
            message="Only queued workflows can be cancelled.",
            details={"workflow_run_id": str(workflow_run_id)},
        )

    queue = cast(WorkflowJobQueue, request.app.state.workflow_job_queue)
    job = await queue.cancel_for_workflow_run(workflow_run_id)
    if job is None or job.status is not JobStatus.CANCELLED:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="workflow_not_cancellable",
            message="The worker has already started this workflow.",
            details={"workflow_run_id": str(workflow_run_id)},
        )

    state = WorkflowState.model_validate(
        {
            "tenant_id": workflow_run.tenant_id,
            "document_id": workflow_run.document_id,
            "document_type": "other",
            "workflow_run_id": workflow_run.id,
            "status": workflow_run.status,
            "current_agent": workflow_run.current_agent,
            **(workflow_run.state or {}),
        }
    )
    WorkflowRuntimeService(repository).update_workflow_status(
        workflow_run=workflow_run,
        state=state,
        status=WorkflowStateStatus.CANCELLED,
    )
    await repository.commit()
    return WorkflowRunStatusResponse.from_model(workflow_run)
