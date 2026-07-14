from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.jobs import WorkflowJob, WorkflowJobStatus


class FakeWorkflowJobRepository:
    def __init__(self, job: WorkflowJob | None) -> None:
        self.job = job
        self.outbox_events: list[object] = []
        self.committed = False

    async def get_job_for_tenant(self, *, job_id, tenant_id, for_update=False):
        del for_update
        if (
            self.job is None
            or self.job.id != job_id
            or self.job.tenant_id != tenant_id
        ):
            return None
        return self.job

    def add_outbox_event(self, event) -> None:
        self.outbox_events.append(event)

    async def commit(self) -> None:
        self.committed = True


def auth_headers(tenant_id, *, role: str) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-User-ID": str(uuid4()),
        "X-User-Role": role,
    }


def published_job(*, tenant_id):
    now = datetime.now(UTC)
    workflow_run_id = uuid4()
    return WorkflowJob(
        id=uuid4(),
        tenant_id=tenant_id,
        workflow_run_id=workflow_run_id,
        document_id=uuid4(),
        idempotency_key=str(workflow_run_id),
        status=WorkflowJobStatus.PUBLISHED.value,
        priority="high",
        command={"workflow_run_id": str(workflow_run_id)},
        celery_task_id="stale-task",
        enqueued_at=now,
        worker_id="old-worker",
        heartbeat_at=now,
        lease_expires_at=now,
    )


def test_admin_can_requeue_published_job(
    app: FastAPI,
    client: TestClient,
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    job = published_job(tenant_id=tenant_id)
    repository = FakeWorkflowJobRepository(job)
    monkeypatch.setattr(
        "app.api.routers.ops.WorkflowJobRepository",
        lambda session: repository,
    )

    response = client.post(
        f"/api/v1/ops/workflow-jobs/{job.id}/requeue",
        headers=auth_headers(tenant_id, role="admin"),
        json={"reason": "Recover message published while the Redis backend was down."},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == str(job.id)
    assert response.json()["workflow_run_id"] == str(job.workflow_run_id)
    assert response.json()["status"] == WorkflowJobStatus.QUEUED.value
    assert repository.committed is True
    assert job.celery_task_id is None
    assert job.enqueued_at is None
    assert job.worker_id is None
    assert job.heartbeat_at is None
    assert job.lease_expires_at is None
    assert len(repository.outbox_events) == 1
    event = repository.outbox_events[0]
    assert event.workflow_job_id == job.id
    assert event.status == "pending"
    assert event.payload == {"command": job.command}


def test_member_cannot_manually_requeue_published_job(
    app: FastAPI,
    client: TestClient,
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    job = published_job(tenant_id=tenant_id)
    repository = FakeWorkflowJobRepository(job)
    monkeypatch.setattr(
        "app.api.routers.ops.WorkflowJobRepository",
        lambda session: repository,
    )

    response = client.post(
        f"/api/v1/ops/workflow-jobs/{job.id}/requeue",
        headers=auth_headers(tenant_id, role="member"),
        json={"reason": "Attempt a manual recovery."},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert repository.outbox_events == []
