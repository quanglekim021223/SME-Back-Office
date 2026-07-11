"""Celery tasks that execute portable document processing commands."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import Task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.jobs.contracts import DocumentProcessingCommand
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

    try:
        asyncio.run(executor.execute(command, mark_failed=False))
    except Exception as exc:
        next_attempt = task.request.retries + 1
        if next_attempt <= settings.celery_task_max_retries:
            asyncio.run(executor.record_retry(command, error=exc))
            countdown = settings.celery_retry_backoff_seconds * (
                2**task.request.retries
            )
            raise task.retry(
                exc=exc,
                countdown=countdown,
                max_retries=settings.celery_task_max_retries,
            ) from exc

        asyncio.run(executor.mark_failed_from_exception(command, error=exc))
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
