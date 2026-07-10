from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.workflow import WorkflowRun, WorkflowRunStatus
from app.workflows.contracts import WorkflowStateStatus


class FakeWorkflowRepository:
    def __init__(self, workflow_run: WorkflowRun | None) -> None:
        self.workflow_run = workflow_run
        self.calls: list[tuple[object, object]] = []

    async def get_for_tenant(self, *, tenant_id, object_id):
        self.calls.append((tenant_id, object_id))
        if self.workflow_run is None or self.workflow_run.tenant_id != tenant_id:
            return None
        return self.workflow_run

    async def commit(self) -> None:
        return None


class FakeWorkflowQueue:
    def __init__(self, *, cancellable_job=None) -> None:
        self.cancellable_job = cancellable_job

    async def get_progress(self, workflow_run_id):
        del workflow_run_id
        return None

    async def cancel_for_workflow_run(self, workflow_run_id):
        del workflow_run_id
        return self.cancellable_job


def auth_headers(tenant_id) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-User-ID": str(uuid4()),
        "X-User-Role": "member",
    }


def test_workflow_run_status_is_tenant_scoped(
    app: FastAPI,
    client: TestClient,
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    workflow_run = WorkflowRun(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=uuid4(),
        workflow_name="document_processing_replay",
        workflow_version="0.1.0",
        status=WorkflowRunStatus.RETRYING.value,
        current_agent="totals_extractor",
        retry_count=1,
        correlation_id="corr-123",
        state={"stage": "totals_extraction"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_repository = FakeWorkflowRepository(workflow_run)
    monkeypatch.setattr(
        "app.api.routers.workflows.WorkflowRuntimeRepository",
        lambda session: fake_repository,
    )

    response = client.get(
        f"/api/v1/workflow-runs/{workflow_run.id}",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "id": str(workflow_run.id),
        "document_id": str(workflow_run.document_id),
        "workflow_name": "document_processing_replay",
        "workflow_version": "0.1.0",
        "status": "retrying",
        "stage": "totals_extraction",
        "current_agent": "totals_extractor",
        "retry_count": 1,
        "correlation_id": "corr-123",
        "error_code": None,
        "error_message": None,
        "created_at": workflow_run.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": workflow_run.updated_at.isoformat().replace("+00:00", "Z"),
        "progress": {
            "phase": "extraction",
            "label": "Verifying invoice totals",
            "percent": 64,
            "current_agent": "totals_extractor",
            "completed_agents": [],
            "is_terminal": False,
        },
    }


def test_workflow_run_status_hides_other_tenant_data(
    app: FastAPI,
    client: TestClient,
    monkeypatch,
) -> None:
    workflow_run = WorkflowRun(
        id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        workflow_name="document_processing_replay",
        workflow_version="0.1.0",
        status=WorkflowRunStatus.QUEUED.value,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_repository = FakeWorkflowRepository(workflow_run)
    monkeypatch.setattr(
        "app.api.routers.workflows.WorkflowRuntimeRepository",
        lambda session: fake_repository,
    )

    response = client.get(
        f"/api/v1/workflow-runs/{workflow_run.id}",
        headers=auth_headers(uuid4()),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workflow_run_not_found"


def test_workflow_run_cancel_marks_queued_run_cancelled(
    app: FastAPI,
    client: TestClient,
    monkeypatch,
) -> None:
    from app.jobs import JobRef, JobStatus

    tenant_id = uuid4()
    workflow_run = WorkflowRun(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=uuid4(),
        workflow_name="document_processing_replay",
        workflow_version="0.1.0",
        status=WorkflowRunStatus.QUEUED.value,
        state={"stage": "ingested"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    fake_repository = FakeWorkflowRepository(workflow_run)
    app.state.workflow_job_queue = FakeWorkflowQueue(
        cancellable_job=JobRef(
            workflow_run_id=workflow_run.id,
            status=JobStatus.CANCELLED,
        )
    )
    monkeypatch.setattr(
        "app.api.routers.workflows.WorkflowRuntimeRepository",
        lambda session: fake_repository,
    )

    response = client.post(
        f"/api/v1/workflow-runs/{workflow_run.id}/cancel",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    assert response.json()["status"] == WorkflowStateStatus.CANCELLED.value
    assert response.json()["progress"]["phase"] == "cancelled"
    assert workflow_run.status == WorkflowRunStatus.CANCELLED.value
