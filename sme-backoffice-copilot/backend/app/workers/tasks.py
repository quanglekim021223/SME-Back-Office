"""Celery tasks that execute portable document processing commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import Task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.db import async_session_factory, dispose_engine
from app.jobs.contracts import DocumentProcessingCommand, WorkflowJobLeaseLostError
from app.services.workflow_jobs import (
    WorkflowJobRuntimeService,
    execute_claimed_workflow_job,
)
from app.workers.celery_app import celery_app
from app.workflows.job_executor import DocumentProcessingWorkflowExecutor
from app.workflows.progress import build_workflow_progress, serialize_workflow_progress

logger = logging.getLogger("app.workflow_worker")


class CeleryTaskProgressReporter:
    """Push non-sensitive workflow phase metadata into Celery's result backend."""

    def __init__(self, task: Task) -> None:
        self._task = task

    def __call__(self, workflow_run: Any, state: Any) -> None:
        del workflow_run
        snapshot = build_workflow_progress(state)
        self._task.update_state(
            state="PROGRESS",
            meta={"progress": serialize_workflow_progress(snapshot)},
        )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="app.workers.execute_document_processing",
)
def execute_document_processing(
    task: Task,
    command_payload: dict[str, object],
) -> None:
    """Run one queued workflow in a worker process and retry transient failures."""

    settings = get_settings()
    command = DocumentProcessingCommand.model_validate(command_payload)
    executor = DocumentProcessingWorkflowExecutor(
        session_factory=async_session_factory,
        settings=settings,
        progress_observer=CeleryTaskProgressReporter(task),
    )
    job_runtime = WorkflowJobRuntimeService(
        async_session_factory,
        lease_seconds=settings.workflow_job_lease_seconds,
    )
    worker_id = ":".join(
        (
            str(task.request.hostname or "celery-worker"),
            str(task.request.id or command.job_id),
        )
    )
    next_attempt = task.request.retries + 1
    retry_allowed = next_attempt <= settings.celery_task_max_retries
    countdown = settings.celery_retry_backoff_seconds * (2**task.request.retries)

    try:
        asyncio.run(
            _run_worker_attempt(
                command=command,
                executor=executor,
                job_runtime=job_runtime,
                worker_id=worker_id,
                heartbeat_seconds=settings.workflow_job_heartbeat_seconds,
                retry_allowed=retry_allowed,
                retry_delay_seconds=countdown,
            )
        )
    except WorkflowJobLeaseLostError:
        logger.warning(
            "workflow.job.stale_worker_fenced",
            extra={
                "event": "workflow.job.stale_worker_fenced",
                "workflow_job_id": str(command.job_id),
                "workflow_run_id": str(command.workflow_run_id),
                "worker_id": worker_id,
                "correlation_id": command.correlation_id,
            },
        )
        return
    except Exception as exc:
        if retry_allowed:
            raise task.retry(
                exc=exc,
                countdown=countdown,
                max_retries=settings.celery_task_max_retries,
            ) from exc

        logger.exception(
            "workflow.job.exhausted",
            extra={
                "event": "workflow.job.exhausted",
                "workflow_run_id": str(command.workflow_run_id),
                "document_id": str(command.document_id),
                "correlation_id": command.correlation_id,
            },
        )
        raise


async def _run_worker_attempt(
    *,
    command: DocumentProcessingCommand,
    executor: DocumentProcessingWorkflowExecutor,
    job_runtime: WorkflowJobRuntimeService,
    worker_id: str,
    heartbeat_seconds: float,
    retry_allowed: bool,
    retry_delay_seconds: float,
) -> None:
    """Use one event loop for claim, execution, retry state, and pool cleanup."""

    try:
        await execute_claimed_workflow_job(
            command=command,
            execute=lambda queued_command: executor.execute(
                queued_command,
                mark_failed=False,
                worker_id=worker_id,
            ),
            job_runtime=job_runtime,
            worker_id=worker_id,
            heartbeat_seconds=heartbeat_seconds,
        )
    except Exception as exc:
        if retry_allowed:
            owns_job = await job_runtime.mark_retrying(
                command,
                error=exc,
                delay_seconds=retry_delay_seconds,
                worker_id=worker_id,
            )
            if not owns_job:
                return
        else:
            owns_job = await job_runtime.mark_dead_lettered(
                command,
                error=exc,
                worker_id=worker_id,
            )
            if not owns_job:
                return
        raise
    finally:
        await dispose_engine()
