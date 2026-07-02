"""Human review task API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, status
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
    ReviewTaskDecisionRequest,
    ReviewTaskDecisionResponse,
    ReviewTaskDetailResponse,
    ReviewTaskListResponse,
    ReviewTaskSummaryResponse,
)
from app.services.review_tasks import (
    ReviewResourceNotFoundError,
    ReviewTaskDecisionError,
    ReviewTaskDecisionResult,
    ReviewTaskDecisionService,
    ReviewTaskListResult,
    ReviewTaskNotActionableError,
    ReviewTaskNotFoundError,
    ReviewTaskQueryService,
    UnsupportedReviewActionError,
)

router = APIRouter(prefix="/review-tasks", tags=["review-tasks"])


def get_review_task_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReviewTaskQueryService:
    """Return the read-only review task query service."""

    return ReviewTaskQueryService.from_session(session)


def get_review_task_decision_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReviewTaskDecisionService:
    """Return the review task decision service."""

    return ReviewTaskDecisionService.from_session(session)


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


@router.post("/{review_task_id}/approve", response_model=ReviewTaskDecisionResponse)
async def approve_review_task_proposal(
    request: Request,
    review_task_id: UUID,
    decision: Annotated[
        ReviewTaskDecisionRequest,
        Body(default_factory=ReviewTaskDecisionRequest),
    ],
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.WRITE_REVIEW_TASKS)),
    ],
    service: Annotated[
        ReviewTaskDecisionService,
        Depends(get_review_task_decision_service),
    ],
) -> ReviewTaskDecisionResponse:
    """Approve the proposal/resource linked to a review task."""

    tenant_id = resolve_tenant_uuid(tenant_context)
    try:
        result = await service.approve_review_task(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            actor=principal,
            comment=decision.comment,
            reason_code=decision.reason_code,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    except ReviewTaskDecisionError as exc:
        raise map_review_decision_error(exc, review_task_id) from exc
    return review_task_decision_response(result)


@router.post("/{review_task_id}/reject", response_model=ReviewTaskDecisionResponse)
async def reject_review_task_proposal(
    request: Request,
    review_task_id: UUID,
    decision: Annotated[
        ReviewTaskDecisionRequest,
        Body(default_factory=ReviewTaskDecisionRequest),
    ],
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.WRITE_REVIEW_TASKS)),
    ],
    service: Annotated[
        ReviewTaskDecisionService,
        Depends(get_review_task_decision_service),
    ],
) -> ReviewTaskDecisionResponse:
    """Reject the proposal/resource linked to a review task."""

    tenant_id = resolve_tenant_uuid(tenant_context)
    try:
        result = await service.reject_review_task(
            tenant_id=tenant_id,
            review_task_id=review_task_id,
            actor=principal,
            comment=decision.comment,
            reason_code=decision.reason_code,
            correlation_id=getattr(request.state, "correlation_id", None),
        )
    except ReviewTaskDecisionError as exc:
        raise map_review_decision_error(exc, review_task_id) from exc
    return review_task_decision_response(result)


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


def review_task_decision_response(
    result: ReviewTaskDecisionResult,
) -> ReviewTaskDecisionResponse:
    """Convert a decision service result into an API response."""

    return ReviewTaskDecisionResponse(
        action=result.action.value,
        review_task=ReviewTaskDetailResponse.from_model(result.review_task),
        resource_type=result.resource_type,
        resource_id=result.resource_id,
        resource_status=result.resource_status,
        audit_event_id=result.audit_event.id,
    )


def map_review_decision_error(
    exc: ReviewTaskDecisionError,
    review_task_id: UUID,
) -> APIError:
    """Map review decision service errors to API errors."""

    if isinstance(exc, ReviewTaskNotFoundError):
        return APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="review_task_not_found",
            message="Review task was not found.",
            details={"review_task_id": str(review_task_id)},
        )
    if isinstance(exc, ReviewTaskNotActionableError):
        return APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="review_task_not_actionable",
            message="Review task is not open or in progress.",
            details={"review_task_id": str(review_task_id)},
        )
    if isinstance(exc, ReviewResourceNotFoundError):
        return APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="review_resource_not_found",
            message="Review task target resource was not found.",
            details={"review_task_id": str(review_task_id)},
        )
    if isinstance(exc, UnsupportedReviewActionError):
        return APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_review_action",
            message="Review task does not support this action.",
            details={"review_task_id": str(review_task_id)},
        )
    return APIError(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="review_decision_failed",
        message="Review decision failed.",
        details={"review_task_id": str(review_task_id)},
    )
