from uuid import uuid4

from app.jobs import (
    DocumentProcessingCommand,
    InProcessWorkflowJobQueue,
    JobPriority,
    JobStatus,
)


def build_command() -> DocumentProcessingCommand:
    return DocumentProcessingCommand(
        workflow_run_id=uuid4(),
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        content_hash="hash-123",
        malware_scan_status="not_scanned",
        priority=JobPriority.HIGH,
    )


async def test_in_process_queue_accepts_and_returns_a_queued_job() -> None:
    queue = InProcessWorkflowJobQueue()
    command = build_command()

    job = await queue.enqueue(command)

    assert job.workflow_run_id == command.workflow_run_id
    assert job.status is JobStatus.QUEUED
    assert job.priority is JobPriority.HIGH
    assert await queue.get(job.job_id) == job
    assert queue.commands == [command]


async def test_in_process_queue_cancels_only_queued_jobs() -> None:
    queue = InProcessWorkflowJobQueue()
    job = await queue.enqueue(build_command())

    cancelled = await queue.cancel(job.job_id)

    assert cancelled is not None
    assert cancelled.status is JobStatus.CANCELLED
    assert await queue.get(job.job_id) == cancelled
