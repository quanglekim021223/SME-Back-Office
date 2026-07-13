from uuid import uuid4

from app.core.config import Settings, WorkflowQueueMode
from app.jobs import DocumentProcessingCommand, JobPriority, JobStatus
from app.jobs.celery import CeleryWorkflowJobQueue
from app.jobs.factory import create_workflow_job_queue


class FakeAsyncResult:
    def __init__(self, *, state: str = "PENDING", info: object = None) -> None:
        self.state = state
        self.info = info


class FakeControl:
    def __init__(self) -> None:
        self.revoked: list[tuple[str, bool]] = []

    def revoke(self, task_id: str, *, terminate: bool) -> None:
        self.revoked.append((task_id, terminate))


class FakeCeleryApp:
    def __init__(self) -> None:
        self.sent_tasks: list[dict[str, object]] = []
        self.results: dict[str, FakeAsyncResult] = {}
        self.control = FakeControl()

    def send_task(self, name: str, **kwargs: object) -> None:
        self.sent_tasks.append({"name": name, **kwargs})

    def AsyncResult(self, task_id: str) -> FakeAsyncResult:
        return self.results.setdefault(task_id, FakeAsyncResult())


def build_command(
    *, priority: JobPriority = JobPriority.HIGH
) -> DocumentProcessingCommand:
    return DocumentProcessingCommand(
        workflow_run_id=uuid4(),
        event_id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        content_hash="hash-123",
        malware_scan_status="not_scanned",
        priority=priority,
    )


async def test_celery_queue_publishes_json_command_to_priority_queue() -> None:
    app = FakeCeleryApp()
    queue = CeleryWorkflowJobQueue(celery_app=app)  # type: ignore[arg-type]
    command = build_command(priority=JobPriority.LOW)

    job = await queue.enqueue(command)

    assert job.status is JobStatus.QUEUED
    assert app.sent_tasks == [
        {
            "name": "app.workers.execute_document_processing",
            "args": [command.model_dump(mode="json")],
            "task_id": str(job.job_id),
            "queue": "document-processing-low",
        }
    ]


async def test_celery_queue_reads_progress_and_running_state() -> None:
    app = FakeCeleryApp()
    queue = CeleryWorkflowJobQueue(celery_app=app)  # type: ignore[arg-type]
    command = build_command()
    job = await queue.enqueue(command)
    app.results[str(job.job_id)] = FakeAsyncResult(
        state="PROGRESS",
        info={
            "progress": {
                "status": "running",
                "stage": "layout_analysis",
                "phase": "ocr",
                "label": "Reading document text",
                "percent": 25,
                "current_agent": "document_layout_analyzer",
                "completed_agents": ["document_intake"],
                "is_terminal": False,
            }
        },
    )

    progress = await queue.get_progress(command.workflow_run_id)

    assert progress is not None
    assert progress.phase == "ocr"
    current = await queue.get(job.job_id)
    assert current is not None
    assert current.status is JobStatus.RUNNING


async def test_celery_queue_revokes_queued_job() -> None:
    app = FakeCeleryApp()
    queue = CeleryWorkflowJobQueue(celery_app=app)  # type: ignore[arg-type]
    job = await queue.enqueue(build_command())

    cancelled = await queue.cancel(job.job_id)

    assert cancelled is not None
    assert cancelled.status is JobStatus.CANCELLED
    assert app.control.revoked == [(str(job.job_id), False)]
    assert await queue.get(job.job_id) == cancelled


def test_queue_factory_selects_celery_without_connecting_to_redis() -> None:
    queue = create_workflow_job_queue(
        Settings(_env_file=None, workflow_queue_mode=WorkflowQueueMode.CELERY)
    )

    assert isinstance(queue, CeleryWorkflowJobQueue)
