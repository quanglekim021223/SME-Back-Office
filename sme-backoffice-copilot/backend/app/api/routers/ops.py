"""Local operations and observability API router."""

import logging
from typing import Annotated
from uuid import UUID, uuid4

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
from app.models.base import utc_now
from app.models.jobs import OutboxEvent, OutboxEventStatus, WorkflowJobStatus
from app.observability.metrics import metrics_registry
from app.repositories.jobs import WorkflowJobRepository
from app.schemas.dashboard import DashboardFinancialSummaryResponse
from app.schemas.workflow import WorkflowJobRequeueRequest, WorkflowJobRequeueResponse
from app.services.dashboard_financial_summary import DashboardFinancialSummaryService
from app.services.workflow_jobs import WorkflowJobMetricsService

router = APIRouter(prefix="/ops", tags=["ops"])
logger = logging.getLogger("app.ops")


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


@router.post(
    "/workflow-jobs/{job_id}/requeue",
    response_model=WorkflowJobRequeueResponse,
)
async def requeue_published_workflow_job(
    job_id: UUID,
    payload: WorkflowJobRequeueRequest,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.MANAGE_WORKFLOWS)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WorkflowJobRequeueResponse:
    """Create a new pending outbox event for one stranded published job."""

    tenant_id = resolve_tenant_uuid(tenant_context)
    repository = WorkflowJobRepository(session)
    job = await repository.get_job_for_tenant(
        job_id=job_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if job is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="workflow_job_not_found",
            message="Workflow job was not found.",
            details={"job_id": str(job_id)},
        )
    if job.status != WorkflowJobStatus.PUBLISHED.value:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="workflow_job_not_requeueable",
            message="Only published workflow jobs can be manually requeued.",
            details={"job_id": str(job_id), "status": job.status},
        )

    now = utc_now()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=tenant_id,
        workflow_job_id=job.id,
        aggregate_type="workflow_run",
        aggregate_id=job.workflow_run_id,
        event_type="DocumentProcessingManualRequeueRequested",
        payload={"command": job.command},
        status=OutboxEventStatus.PENDING.value,
        available_at=now,
    )
    repository.add_outbox_event(event)
    job.status = WorkflowJobStatus.QUEUED.value
    job.celery_task_id = None
    job.enqueued_at = None
    job.worker_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    await repository.commit()

    logger.warning(
        "workflow.job.manually_requeued",
        extra={
            "event": "workflow.job.manually_requeued",
            "workflow_job_id": str(job.id),
            "workflow_run_id": str(job.workflow_run_id),
            "tenant_id": str(tenant_id),
            "actor_id": principal.user_id,
            "reason": payload.reason,
        },
    )
    return WorkflowJobRequeueResponse(
        job_id=job.id,
        workflow_run_id=job.workflow_run_id,
        status=job.status,
        outbox_event_id=event.id,
    )


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
