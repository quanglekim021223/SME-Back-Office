"""Composition helper for selectable workflow queue runtimes."""

from app.core.config import Settings, WorkflowQueueMode
from app.jobs.celery import CeleryWorkflowJobQueue
from app.jobs.in_process import InProcessWorkflowJobQueue
from app.workers.celery_app import create_celery_app


def create_workflow_job_queue(
    settings: Settings,
) -> InProcessWorkflowJobQueue | CeleryWorkflowJobQueue:
    """Build the configured adapter while keeping routes implementation-free."""

    if settings.workflow_queue_mode is WorkflowQueueMode.CELERY:
        return CeleryWorkflowJobQueue(celery_app=create_celery_app(settings))
    return InProcessWorkflowJobQueue()
