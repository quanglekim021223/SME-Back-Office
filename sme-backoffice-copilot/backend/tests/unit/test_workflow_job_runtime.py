import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from app.jobs import (
    DocumentProcessingCommand,
    JobPriority,
    WorkflowJobLeaseLostError,
)
from app.models.base import utc_now
from app.models.jobs import (
    OutboxEvent,
    OutboxEventStatus,
    WorkflowJob,
    WorkflowJobStatus,
)
from app.models.workflow import WorkflowRun, WorkflowRunStatus
from app.services.workflow_jobs import (
    JobClaim,
    OutboxDispatcher,
    execute_claimed_workflow_job,
)
from app.workflows.contracts import WorkflowState
from app.workflows.job_executor import DocumentProcessingWorkflowExecutor


def build_command() -> DocumentProcessingCommand:
    workflow_run_id = uuid4()
    return DocumentProcessingCommand(
        job_id=workflow_run_id,
        workflow_run_id=workflow_run_id,
        event_id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        storage_uri="local://invoice.png",
        content_hash="hash-123",
        malware_scan_status="clean",
    )


class FakeJobRuntime:
    def __init__(self, claim: JobClaim) -> None:
        self.claim_result = claim
        self.heartbeats = 0
        self.succeeded: list[object] = []

    async def claim(self, command, *, worker_id):
        del command, worker_id
        return self.claim_result

    async def heartbeat(self, job_id, *, worker_id):
        del job_id, worker_id
        self.heartbeats += 1
        return True

    async def mark_succeeded(self, job_id):
        self.succeeded.append(job_id)


@pytest.mark.asyncio
async def test_duplicate_active_job_is_not_executed() -> None:
    command = build_command()
    runtime = FakeJobRuntime(JobClaim(claimed=False, reason="active_lease"))
    executions = 0

    async def execute(queued_command):
        nonlocal executions
        del queued_command
        executions += 1

    claim = await execute_claimed_workflow_job(
        command=command,
        execute=execute,
        job_runtime=runtime,  # type: ignore[arg-type]
        worker_id="worker-1",
        heartbeat_seconds=0.001,
    )

    assert claim.reason == "active_lease"
    assert executions == 0
    assert runtime.succeeded == []


@pytest.mark.asyncio
async def test_claimed_job_heartbeats_and_finishes_once() -> None:
    command = build_command()
    runtime = FakeJobRuntime(JobClaim(claimed=True, reason="claimed", attempt_count=1))

    async def execute(queued_command):
        assert queued_command == command
        await asyncio.sleep(0.005)

    await execute_claimed_workflow_job(
        command=command,
        execute=execute,
        job_runtime=runtime,  # type: ignore[arg-type]
        worker_id="worker-1",
        heartbeat_seconds=0.001,
    )

    assert runtime.heartbeats >= 1
    assert runtime.succeeded == [command.job_id]


@pytest.mark.asyncio
async def test_failed_execution_is_not_marked_succeeded() -> None:
    command = build_command()
    runtime = FakeJobRuntime(JobClaim(claimed=True, reason="claimed", attempt_count=1))

    async def execute(queued_command):
        del queued_command
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await execute_claimed_workflow_job(
            command=command,
            execute=execute,
            job_runtime=runtime,  # type: ignore[arg-type]
            worker_id="worker-1",
            heartbeat_seconds=0.001,
        )

    assert runtime.succeeded == []


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback

    async def commit(self) -> None:
        self.commits += 1


class FakeRecoveryRepository:
    job: WorkflowJob
    workflow_run: WorkflowRun
    outbox_events: list[object]

    def __init__(self, session) -> None:
        del session

    async def list_stale_running_jobs(self, *, now, limit):
        del now, limit
        return [self.job]

    async def get_workflow_run_unscoped(self, workflow_run_id):
        assert workflow_run_id == self.workflow_run.id
        return self.workflow_run

    def add_outbox_event(self, event):
        self.outbox_events.append(event)
        return event


class FakeWorkflowRuntime:
    def __init__(self, repository) -> None:
        del repository

    def update_workflow_status(self, *, workflow_run, state, status, **kwargs):
        del state, kwargs
        workflow_run.status = status.value


class UnusedQueue:
    async def enqueue(self, command):
        raise AssertionError(f"Unexpected enqueue for {command}")


@pytest.mark.asyncio
async def test_expired_worker_lease_is_marked_lost_and_redelivered(
    monkeypatch,
) -> None:
    command = build_command().model_copy(update={"priority": JobPriority.HIGH})
    state = WorkflowState(
        tenant_id=command.tenant_id,
        document_id=command.document_id,
        document_type=command.document_type,
        workflow_run_id=command.workflow_run_id,
    )
    FakeRecoveryRepository.job = WorkflowJob(
        id=command.job_id,
        tenant_id=command.tenant_id,
        workflow_run_id=command.workflow_run_id,
        document_id=command.document_id,
        idempotency_key=str(command.workflow_run_id),
        status=WorkflowJobStatus.RUNNING.value,
        priority=command.priority.value,
        command=command.model_dump(mode="json"),
        attempt_count=1,
        max_attempts=3,
        available_at=utc_now(),
        lease_expires_at=utc_now() - timedelta(seconds=1),
    )
    FakeRecoveryRepository.workflow_run = WorkflowRun(
        id=command.workflow_run_id,
        tenant_id=command.tenant_id,
        document_id=command.document_id,
        workflow_name="document_processing_replay",
        workflow_version="0.1.0",
        status=WorkflowRunStatus.RUNNING.value,
        state=state.model_dump(mode="json"),
    )
    FakeRecoveryRepository.outbox_events = []
    session = FakeSession()
    monkeypatch.setattr(
        "app.services.workflow_jobs.WorkflowJobRepository",
        FakeRecoveryRepository,
    )
    monkeypatch.setattr(
        "app.services.workflow_jobs.WorkflowRuntimeService",
        FakeWorkflowRuntime,
    )
    dispatcher = OutboxDispatcher(
        session_factory=lambda: session,  # type: ignore[arg-type]
        queue=UnusedQueue(),  # type: ignore[arg-type]
        batch_size=10,
        retry_backoff_seconds=1,
    )

    recovered = await dispatcher.recover_stale_jobs()

    assert recovered == 1
    assert FakeRecoveryRepository.job.status == WorkflowJobStatus.LOST.value
    assert FakeRecoveryRepository.workflow_run.status == WorkflowRunStatus.LOST.value
    assert len(FakeRecoveryRepository.outbox_events) == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_output_commit_fences_worker_that_lost_its_lease(monkeypatch) -> None:
    command = build_command()
    job = WorkflowJob(
        id=command.job_id,
        tenant_id=command.tenant_id,
        workflow_run_id=command.workflow_run_id,
        document_id=command.document_id,
        idempotency_key=str(command.workflow_run_id),
        status=WorkflowJobStatus.LOST.value,
        priority=command.priority.value,
        command=command.model_dump(mode="json"),
        attempt_count=1,
        max_attempts=3,
        available_at=utc_now(),
        worker_id="replacement-worker",
    )

    class FakeLeaseRepository:
        def __init__(self, session) -> None:
            del session

        async def get_job(self, job_id, *, for_update=False):
            assert job_id == command.job_id
            assert for_update is True
            return job

    monkeypatch.setattr(
        "app.workflows.job_executor.WorkflowJobRepository",
        FakeLeaseRepository,
    )

    with pytest.raises(WorkflowJobLeaseLostError):
        await DocumentProcessingWorkflowExecutor._complete_job_with_output(
            session=object(),  # type: ignore[arg-type]
            command=command,
            worker_id="stale-worker",
        )


@pytest.mark.asyncio
async def test_outbox_keeps_event_pending_when_queue_is_unavailable(
    monkeypatch,
) -> None:
    command = build_command()
    job = WorkflowJob(
        id=command.job_id,
        tenant_id=command.tenant_id,
        workflow_run_id=command.workflow_run_id,
        document_id=command.document_id,
        idempotency_key=str(command.workflow_run_id),
        status=WorkflowJobStatus.QUEUED.value,
        priority=command.priority.value,
        command=command.model_dump(mode="json"),
        attempt_count=0,
        max_attempts=3,
        available_at=utc_now(),
    )
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=command.tenant_id,
        workflow_job_id=job.id,
        aggregate_type="workflow_run",
        aggregate_id=command.workflow_run_id,
        event_type="DocumentProcessingRequested",
        payload={"command": command.model_dump(mode="json")},
        status=OutboxEventStatus.PENDING.value,
        attempt_count=0,
        available_at=utc_now(),
    )
    initial_available_at = event.available_at

    class FakeDispatchRepository:
        def __init__(self, session) -> None:
            del session

        async def list_dispatchable_outbox(self, *, now, limit):
            del now, limit
            return [event]

        async def get_job(self, job_id, *, for_update=False):
            assert job_id == job.id
            assert for_update is True
            return job

    class FailingQueue:
        async def enqueue(self, queued_command):
            assert queued_command == command
            raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(
        "app.services.workflow_jobs.WorkflowJobRepository",
        FakeDispatchRepository,
    )
    session = FakeSession()
    dispatcher = OutboxDispatcher(
        session_factory=lambda: session,  # type: ignore[arg-type]
        queue=FailingQueue(),  # type: ignore[arg-type]
        batch_size=10,
        retry_backoff_seconds=2,
    )

    published = await dispatcher.dispatch_once()

    assert published == 0
    assert event.status == OutboxEventStatus.PENDING.value
    assert event.attempt_count == 1
    assert event.available_at > initial_available_at
    assert job.status == WorkflowJobStatus.QUEUED.value
    assert session.commits == 1
