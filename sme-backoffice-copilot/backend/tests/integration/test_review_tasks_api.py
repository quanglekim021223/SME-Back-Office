from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.review_tasks import (
    get_review_task_decision_service,
    get_review_task_query_service,
)
from app.models.base import utc_now
from app.models.operations import (
    AuditEvent,
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.review import ReviewAction
from app.services.review_tasks import (
    InvalidReviewCorrectionError,
    ReviewTaskCorrectionResult,
    ReviewTaskDecisionResult,
    ReviewTaskListResult,
    ReviewTaskNotActionableError,
)


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


class FakeReviewTaskDecisionService:
    def __init__(
        self,
        *,
        result: ReviewTaskDecisionResult | ReviewTaskCorrectionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.approve_calls: list[dict[str, object]] = []
        self.reject_calls: list[dict[str, object]] = []
        self.correct_extraction_calls: list[dict[str, object]] = []
        self.correct_classification_calls: list[dict[str, object]] = []
        self.correct_reconciliation_calls: list[dict[str, object]] = []

    async def approve_review_task(self, **kwargs) -> ReviewTaskDecisionResult:
        self.approve_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def reject_review_task(self, **kwargs) -> ReviewTaskDecisionResult:
        self.reject_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def correct_extracted_fields(self, **kwargs) -> ReviewTaskCorrectionResult:
        self.correct_extraction_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert isinstance(self.result, ReviewTaskCorrectionResult)
        return self.result

    async def correct_classification(self, **kwargs) -> ReviewTaskCorrectionResult:
        self.correct_classification_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert isinstance(self.result, ReviewTaskCorrectionResult)
        return self.result

    async def correct_reconciliation(self, **kwargs) -> ReviewTaskCorrectionResult:
        self.correct_reconciliation_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert isinstance(self.result, ReviewTaskCorrectionResult)
        return self.result


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


def override_review_decision_service(
    app: FastAPI,
    service: FakeReviewTaskDecisionService,
) -> None:
    app.dependency_overrides[get_review_task_decision_service] = lambda: service


def build_decision_result(
    *,
    task: ReviewTask,
    action: ReviewAction,
) -> ReviewTaskDecisionResult:
    task.status = ReviewTaskStatus.RESOLVED.value
    task.resolved_at = utc_now()
    audit_event = AuditEvent(
        id=uuid4(),
        tenant_id=task.tenant_id,
        action="review_task.approved"
        if action == ReviewAction.APPROVE_PROPOSAL
        else "review_task.rejected",
        resource_type=task.target_type,
        resource_id=task.classification_proposal_id,
    )
    return ReviewTaskDecisionResult(
        action=action,
        review_task=task,
        resource_type=task.target_type,
        resource_id=task.classification_proposal_id or uuid4(),
        resource_status="approved"
        if action == ReviewAction.APPROVE_PROPOSAL
        else "rejected",
        audit_event=audit_event,
    )


def build_correction_result(
    *,
    task: ReviewTask,
    action: ReviewAction,
) -> ReviewTaskCorrectionResult:
    superseded_resource_id = task.classification_proposal_id or uuid4()
    replacement_resource_id = uuid4()
    task.status = ReviewTaskStatus.RESOLVED.value
    task.resolved_at = utc_now()
    task.classification_proposal_id = replacement_resource_id
    audit_event = AuditEvent(
        id=uuid4(),
        tenant_id=task.tenant_id,
        action=f"review_task.{action.value}",
        resource_type=task.target_type,
        resource_id=replacement_resource_id,
    )
    return ReviewTaskCorrectionResult(
        action=action,
        review_task=task,
        resource_type=task.target_type,
        superseded_resource_id=superseded_resource_id,
        replacement_resource_id=replacement_resource_id,
        replacement_resource_status="proposed",
        audit_event=audit_event,
    )


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


def test_approve_review_task_endpoint_returns_decision_payload(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(tenant_id=tenant_id)
    fake_service = FakeReviewTaskDecisionService(
        result=build_decision_result(
            task=task,
            action=ReviewAction.APPROVE_PROPOSAL,
        )
    )
    override_review_decision_service(app, fake_service)

    response = client.post(
        f"/api/v1/review-tasks/{task.id}/approve",
        headers=auth_headers(tenant_id),
        json={
            "comment": "Looks good.",
            "reason_code": "APPROVED_BY_ACCOUNTANT",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == ReviewAction.APPROVE_PROPOSAL.value
    assert payload["review_task"]["id"] == str(task.id)
    assert payload["review_task"]["status"] == ReviewTaskStatus.RESOLVED.value
    assert payload["resource_type"] == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    assert payload["resource_id"] == str(task.classification_proposal_id)
    assert payload["resource_status"] == "approved"
    assert payload["audit_event_id"]
    assert fake_service.approve_calls[0]["comment"] == "Looks good."
    assert fake_service.approve_calls[0]["reason_code"] == "APPROVED_BY_ACCOUNTANT"
    assert fake_service.approve_calls[0]["tenant_id"] == tenant_id


def test_reject_review_task_endpoint_maps_not_actionable_to_conflict(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(tenant_id=tenant_id)
    fake_service = FakeReviewTaskDecisionService(
        error=ReviewTaskNotActionableError("already resolved")
    )
    override_review_decision_service(app, fake_service)

    response = client.post(
        f"/api/v1/review-tasks/{task.id}/reject",
        headers=auth_headers(tenant_id),
        json={"comment": "Too late."},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["code"] == "review_task_not_actionable"
    assert payload["error"]["details"] == {"review_task_id": str(task.id)}


def test_correct_classification_endpoint_returns_correction_payload(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(tenant_id=tenant_id)
    fake_service = FakeReviewTaskDecisionService(
        result=build_correction_result(
            task=task,
            action=ReviewAction.CORRECT_CLASSIFICATION,
        )
    )
    override_review_decision_service(app, fake_service)
    new_category_id = uuid4()

    response = client.post(
        f"/api/v1/review-tasks/{task.id}/correct-classification",
        headers=auth_headers(tenant_id),
        json={
            "proposed_category_id": str(new_category_id),
            "confidence": "high",
            "rationale": "Corrected category.",
            "comment": "Move to the right category.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == ReviewAction.CORRECT_CLASSIFICATION.value
    assert payload["review_task"]["id"] == str(task.id)
    assert payload["review_task"]["status"] == ReviewTaskStatus.RESOLVED.value
    assert payload["resource_type"] == ReviewTargetType.CLASSIFICATION_PROPOSAL.value
    assert payload["superseded_resource_id"]
    assert payload["replacement_resource_id"]
    assert payload["replacement_resource_status"] == "proposed"
    assert payload["audit_event_id"]
    call = fake_service.correct_classification_calls[0]
    assert call["tenant_id"] == tenant_id
    assert call["comment"] == "Move to the right category."
    assert call["corrected_fields"]["proposed_category_id"] == new_category_id
    assert call["corrected_fields"]["confidence"] == "high"


def test_correct_extraction_endpoint_maps_invalid_correction_to_bad_request(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    task = build_review_task(
        tenant_id=tenant_id,
        task_type=ReviewTaskType.EXTRACTION,
        target_type=ReviewTargetType.INVOICE,
    )
    fake_service = FakeReviewTaskDecisionService(
        error=InvalidReviewCorrectionError("Unsupported invoice correction fields.")
    )
    override_review_decision_service(app, fake_service)

    response = client.post(
        f"/api/v1/review-tasks/{task.id}/correct-extraction",
        headers=auth_headers(tenant_id),
        json={"corrected_fields": {"tenant_id": str(uuid4())}},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "invalid_review_correction"
    assert payload["error"]["details"] == {"review_task_id": str(task.id)}
