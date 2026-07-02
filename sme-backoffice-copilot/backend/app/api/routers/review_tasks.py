"""Human review task API router."""

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
from app.models.operations import ReviewTaskStatus, ReviewTaskType
from app.schemas.review import (
    ReviewTaskDetailResponse,
    ReviewTaskListResponse,
    ReviewTaskSummaryResponse,
)
from app.services.review_tasks import ReviewTaskListResult, ReviewTaskQueryService

router = APIRouter(prefix="/review-tasks", tags=["review-tasks"])


def get_review_task_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReviewTaskQueryService:
    """Return the read-only review task query service."""

    return ReviewTaskQueryService.from_session(session)


@router.get("", response_model=ReviewTaskListResponse)
async def list_review_tasks(
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_REVIEW_TASKS)),
    ],
    service: Annotated[
        ReviewTaskQueryService,
        Depends(get_review_task_query_service),
    ],
    status_filter: Annotated[
        ReviewTaskStatus | None,
        Query(alias="status"),
    ] = None,
    task_type: Annotated[
        ReviewTaskType | None,
        Query(alias="task_type"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReviewTaskListResponse:
    """List tenant-scoped human review tasks."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    result = await service.list_review_tasks(
        tenant_id=tenant_id,
        status_filter=status_filter,
        task_type=task_type,
        limit=limit,
        offset=offset,
    )
    return review_task_list_response(result)


@router.get("/{review_task_id}", response_model=ReviewTaskDetailResponse)
async def get_review_task_detail(
    review_task_id: UUID,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_REVIEW_TASKS)),
    ],
    service: Annotated[
        ReviewTaskQueryService,
        Depends(get_review_task_query_service),
    ],
) -> ReviewTaskDetailResponse:
    """Inspect one tenant-scoped human review task."""

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    task = await service.get_review_task(
        tenant_id=tenant_id,
        review_task_id=review_task_id,
    )
    if task is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="review_task_not_found",
            message="Review task was not found.",
            details={"review_task_id": str(review_task_id)},
        )
    return ReviewTaskDetailResponse.from_model(task)


def review_task_list_response(
    result: ReviewTaskListResult,
) -> ReviewTaskListResponse:
    """Convert a service list result into an API response."""

    return ReviewTaskListResponse(
        items=[ReviewTaskSummaryResponse.from_model(task) for task in result.tasks],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )
