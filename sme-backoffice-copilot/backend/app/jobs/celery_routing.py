"""Celery task and queue names for document processing infrastructure."""

from app.jobs.contracts import JobPriority

DOCUMENT_PROCESSING_TASK_NAME = "app.workers.execute_document_processing"

CELERY_QUEUE_BY_PRIORITY: dict[JobPriority, str] = {
    JobPriority.HIGH: "document-processing-high",
    JobPriority.MEDIUM: "document-processing-medium",
    JobPriority.LOW: "document-processing-low",
}


def celery_queue_name(priority: JobPriority) -> str:
    """Return the physical Celery queue selected for one job priority."""

    return CELERY_QUEUE_BY_PRIORITY[priority]
