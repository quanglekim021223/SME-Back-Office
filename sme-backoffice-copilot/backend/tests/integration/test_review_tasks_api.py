from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.review_tasks import get_review_task_query_service
from app.models.base import utc_now
from app.models.operations import (
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.services.review_tasks import ReviewTaskListResult


class FakeReviewTaskQueryService:
    def __init__(self, tasks: list[ReviewTask]) -> None:
        self.tasks = tasks
        self.list_calls: list[dict[str, object]] = []
        self.detail_calls: list[dict[str, object]] = []

    async def list_review_tasks(
        self,
        *,
        tenant_id: UUID,
        status_filter: ReviewTaskStatus | None = None,
        task_type: ReviewTaskType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewTaskListResult:
        self.list_calls.append(
            {
                "tenant_id": tenant_id,
                "status_filter": status_filter,
                "task_type": task_type,
                "limit": limit,
                "offset": offset,
            }
        )
        filtered_tasks = [
            task
            for task in self.tasks
            if task.tenant_id == tenant_id
            and (status_filter is None or task.status == status_filter.value)
            and (task_type is None or task.task_type == task_type.value)
        ]
        return ReviewTaskListResult(
            tasks=filtered_tasks[offset : offset + limit],
            total=len(filtered_tasks),
            limit=limit,
            offset=offset,
        )

    async def get_review_task(
        self,
        *,
        tenant_id: UUID,
        review_task_id: UUID,
    ) -> ReviewTask | None:
        self.detail_calls.append(
            {"tenant_id": tenant_id, "review_task_id": review_task_id}
        )
        return next(
            (
                task
                for task in self.tasks
                if task.tenant_id == tenant_id and task.id == review_task_id
            ),
            None,
        )


def auth_headers(tenant_id: UUID):
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-User-ID": str(uuid4()),
        "X-User-Role": "member",
    }


def build_review_task(
    *,
    tenant_id: UUID,
    task_id: UUID | None = None,
    task_type: ReviewTaskType = ReviewTaskType.CLASSIFICATION,
    target_type: ReviewTargetType = ReviewTargetType.CLASSIFICATION_PROPOSAL,
    status: ReviewTaskStatus = ReviewTaskStatus.OPEN,
) -> ReviewTask:
    now = utc_now()
    return ReviewTask(
        id=task_id or uuid4(),
        tenant_id=tenant_id,
        task_type=task_type.value,
        target_type=target_type.value,
        status=status.value,
        priority=ReviewTaskPriority.HIGH.value,
        title="Review accounting classification",
        description="Classifier confidence is below approval threshold.",
        reason_code="LOW_CLASSIFICATION_CONFIDENCE",
        due_at=now + timedelta(days=2),
        source_agent="classification_agent",
        source_agent_version="0.1.0",
        evidence_refs=["fixture:classification:proposal:1"],
        metadata_={"confidence": "medium"},
        created_at=now,
        updated_at=now,
        classification_proposal_id=uuid4(),
    )


def override_review_service(app: FastAPI, service: FakeReviewTaskQueryService) -> None:
    app.dependency_overrides[get_review_task_query_service] = lambda: service


def test_list_review_tasks_endpoint_returns_tenant_scoped_queue(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    task = build_review_task(tenant_id=tenant_id)
    fake_service = FakeReviewTaskQueryService(
        tasks=[
            task,
            build_review_task(tenant_id=other_tenant_id),
        ]
    )
    override_review_service(app, fake_service)

    response = client.get(
        "/api/v1/review-tasks?status=open&task_type=classification&limit=10&offset=0",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == str(task.id)
    assert payload["items"][0]["tenant_id"] == str(tenant_id)
    assert payload["items"][0]["task_type"] == ReviewTaskType.CLASSIFICATION.value
    assert payload["items"][0]["target_type"] == (
        ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    )
    assert payload["items"][0]["evidence_refs"] == ["fixture:classification:proposal:1"]
    assert fake_service.list_calls[0]["status_filter"] == ReviewTaskStatus.OPEN
    assert fake_service.list_calls[0]["task_type"] == ReviewTaskType.CLASSIFICATION


def test_get_review_task_detail_endpoint_returns_full_task_payload(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(tenant_id=tenant_id)
    fake_service = FakeReviewTaskQueryService(tasks=[task])
    override_review_service(app, fake_service)

    response = client.get(
        f"/api/v1/review-tasks/{task.id}",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(task.id)
    assert payload["description"] == (
        "Classifier confidence is below approval threshold."
    )
    assert payload["reason_code"] == "LOW_CLASSIFICATION_CONFIDENCE"
    assert payload["source_agent"] == "classification_agent"
    assert payload["source_agent_version"] == "0.1.0"
    assert payload["classification_proposal_id"] == str(task.classification_proposal_id)
    assert payload["metadata"] == {"confidence": "medium"}
    assert fake_service.detail_calls[0]["review_task_id"] == task.id


def test_get_review_task_detail_endpoint_returns_not_found_for_other_tenant(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(tenant_id=uuid4())
    fake_service = FakeReviewTaskQueryService(tasks=[task])
    override_review_service(app, fake_service)

    response = client.get(
        f"/api/v1/review-tasks/{task.id}",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "review_task_not_found"
    assert payload["error"]["details"] == {"review_task_id": str(task.id)}


def test_list_review_tasks_endpoint_requires_authenticated_user(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    fake_service = FakeReviewTaskQueryService(tasks=[])
    override_review_service(app, fake_service)

    response = client.get(
        "/api/v1/review-tasks",
        headers={"X-Tenant-ID": str(tenant_id)},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
