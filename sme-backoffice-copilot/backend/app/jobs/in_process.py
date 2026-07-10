"""In-memory implementation of the workflow job queue for local development."""

from __future__ import annotations

from uuid import UUID

from app.jobs.contracts import (
    DocumentProcessingCommand,
    JobRef,
    JobStatus,
)


class InProcessWorkflowJobQueue:
    """Retain accepted jobs in memory without coupling application code to Celery.

    Cumulative Phase 13 work will attach a local worker to this adapter. Keeping
    enqueue/cancel semantics here first makes the later Celery adapter directly
    substitutable and easy to test.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRef] = {}
        self.commands: list[DocumentProcessingCommand] = []

    async def enqueue(self, command: DocumentProcessingCommand) -> JobRef:
        """Store a queued job and preserve its command for a local worker."""

        job = JobRef(
            workflow_run_id=command.workflow_run_id,
            priority=command.priority,
        )
        self._jobs[job.job_id] = job
        self.commands.append(command)
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
