"""In-memory implementation of the workflow job queue for local development."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.jobs.contracts import (
    DocumentProcessingCommand,
    JobRef,
    JobStatus,
    WorkflowJobHandler,
)

logger = logging.getLogger("app.workflow_queue")


class InProcessWorkflowJobQueue:
    """Retain accepted jobs in memory without coupling application code to Celery.

    The adapter owns a lightweight asyncio worker for local development. It is
    intentionally an adapter detail: callers only interact with the queue
    contract, exactly as they will with the Celery implementation later.
    """

    def __init__(self, handler: WorkflowJobHandler | None = None) -> None:
        self._jobs: dict[UUID, JobRef] = {}
        self._pending: asyncio.Queue[tuple[UUID, DocumentProcessingCommand]] = (
            asyncio.Queue()
        )
        self._handler = handler
        self._worker_task: asyncio.Task[None] | None = None
        self.commands: list[DocumentProcessingCommand] = []

    async def start(self) -> None:
        """Start the local worker once application startup has completed."""

        if self._handler is None or self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(
            self._run_worker(),
            name="document-processing-in-process-worker",
        )

    async def stop(self) -> None:
        """Stop the local worker during application shutdown."""

        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        finally:
            self._worker_task = None

    async def enqueue(self, command: DocumentProcessingCommand) -> JobRef:
        """Store a queued job and preserve its command for a local worker."""

        job = JobRef(
            workflow_run_id=command.workflow_run_id,
            priority=command.priority,
        )
        self._jobs[job.job_id] = job
        self.commands.append(command)
        await self._pending.put((job.job_id, command))
        return job

    async def get(self, job_id: UUID) -> JobRef | None:
        """Return the job retained by this in-memory adapter."""

        return self._jobs.get(job_id)

    async def cancel(self, job_id: UUID) -> JobRef | None:
        """Cancel a job only while it has not started running."""

        job = self._jobs.get(job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return job

        cancelled = job.model_copy(update={"status": JobStatus.CANCELLED})
        self._jobs[job_id] = cancelled
        return cancelled

    async def wait_until_idle(self) -> None:
        """Wait until the local worker has drained all accepted jobs."""

        await self._pending.join()

    async def _run_worker(self) -> None:
        """Execute queued commands without blocking the HTTP request lifecycle."""

        while True:
            job_id, command = await self._pending.get()
            try:
                job = self._jobs.get(job_id)
                if job is None or job.status is JobStatus.CANCELLED:
                    continue

                self._jobs[job_id] = job.model_copy(
                    update={"status": JobStatus.RUNNING}
                )
                try:
                    assert self._handler is not None
                    await self._handler(command)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "workflow.job.failed",
                        extra={
                            "event": "workflow.job.failed",
                            "job_id": str(job_id),
                            "workflow_run_id": str(command.workflow_run_id),
                            "document_id": str(command.document_id),
                            "correlation_id": command.correlation_id,
                        },
                    )
                    current = self._jobs.get(job_id)
                    if current is not None and current.status is JobStatus.RUNNING:
                        self._jobs[job_id] = current.model_copy(
                            update={"status": JobStatus.FAILED}
                        )
                else:
                    current = self._jobs.get(job_id)
                    if current is not None and current.status is JobStatus.RUNNING:
                        self._jobs[job_id] = current.model_copy(
                            update={"status": JobStatus.SUCCEEDED}
                        )
            finally:
                self._pending.task_done()
