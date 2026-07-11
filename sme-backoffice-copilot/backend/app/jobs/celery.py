"""Celery/Redis adapter for the application workflow job queue boundary."""

from __future__ import annotations

from uuid import UUID

from celery import Celery, states  # type: ignore[import-untyped]

from app.jobs.celery_routing import DOCUMENT_PROCESSING_TASK_NAME, celery_queue_name
from app.jobs.contracts import DocumentProcessingCommand, JobRef, JobStatus
from app.workflows.progress import (
    WorkflowProgressSnapshot,
    workflow_progress_from_payload,
)


class CeleryWorkflowJobQueue:
    """Publish portable workflow commands to Celery without leaking it to routes."""

    def __init__(
        self,
        *,
        celery_app: Celery,
        task_name: str = DOCUMENT_PROCESSING_TASK_NAME,
    ) -> None:
        self._celery_app = celery_app
        self._task_name = task_name
        # This short-lived index supports status/progress/cancellation from the
        # accepting API process. Durable job indexing belongs to Phase 13.3.
        self._jobs: dict[UUID, JobRef] = {}
        self._job_ids_by_workflow_run: dict[UUID, UUID] = {}

    async def enqueue(self, command: DocumentProcessingCommand) -> JobRef:
        """Send a JSON-safe command to the priority-specific Celery queue."""

        job = JobRef(
            workflow_run_id=command.workflow_run_id,
            priority=command.priority,
        )
        self._celery_app.send_task(
            self._task_name,
            args=[command.model_dump(mode="json")],
            task_id=str(job.job_id),
            queue=celery_queue_name(command.priority),
        )
        self._jobs[job.job_id] = job
        self._job_ids_by_workflow_run[command.workflow_run_id] = job.job_id
        return job

    async def get(self, job_id: UUID) -> JobRef | None:
        """Map Celery result states back to the portable job contract."""

        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status is JobStatus.CANCELLED:
            return job

        result = self._celery_app.AsyncResult(str(job_id))
        return job.model_copy(update={"status": _job_status_from_celery(result.state)})

    async def cancel(self, job_id: UUID) -> JobRef | None:
        """Revoke a queued Celery task without terminating running work."""

        job = await self.get(job_id)
        if job is None or job.status is not JobStatus.QUEUED:
            return job

        self._celery_app.control.revoke(str(job_id), terminate=False)
        cancelled = job.model_copy(update={"status": JobStatus.CANCELLED})
        self._jobs[job_id] = cancelled
        return cancelled

    async def cancel_for_workflow_run(self, workflow_run_id: UUID) -> JobRef | None:
        """Cancel the API-process job reference for a durable workflow run."""

        job_id = self._job_ids_by_workflow_run.get(workflow_run_id)
        return await self.cancel(job_id) if job_id is not None else None

    async def get_progress(
        self,
        workflow_run_id: UUID,
    ) -> WorkflowProgressSnapshot | None:
        """Read worker-reported progress metadata from the Celery backend."""

        job_id = self._job_ids_by_workflow_run.get(workflow_run_id)
        if job_id is None:
            return None
        result = self._celery_app.AsyncResult(str(job_id))
        info = result.info
        if result.state != "PROGRESS" or not isinstance(info, dict):
            return None
        progress = info.get("progress")
        if not isinstance(progress, dict):
            return None
        try:
            return workflow_progress_from_payload(progress)
        except ValueError:
            return None


def _job_status_from_celery(celery_status: str) -> JobStatus:
    """Translate Celery states at the infrastructure boundary."""

    if celery_status == states.SUCCESS:
        return JobStatus.SUCCEEDED
    if celery_status == states.FAILURE:
        return JobStatus.FAILED
    if celery_status == states.RETRY:
        return JobStatus.RETRYING
    if celery_status == states.REVOKED:
        return JobStatus.CANCELLED
    if celery_status in {states.STARTED, "PROGRESS"}:
        return JobStatus.RUNNING
    return JobStatus.QUEUED
