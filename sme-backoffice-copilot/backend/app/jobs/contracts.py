"""Application-level contracts for document processing jobs.

These contracts deliberately contain no Celery or Redis concepts. HTTP routes
and application services can publish work through this boundary while runtime
adapters decide whether that work runs in-process or on a distributed worker.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.progress import WorkflowProgressSnapshot


class JobStatus(StrEnum):
    """Lifecycle states of a queue job, distinct from business review state."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    LOST = "lost"


class JobPriority(StrEnum):
    """Intent carried by a job; routing is implemented by a later adapter."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DocumentProcessingCommand(BaseModel):
    """Portable payload used to execute one document processing workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "document-processing-command.v1"
    workflow_run_id: UUID
    event_id: UUID
    tenant_id: UUID
    document_id: UUID
    document_type: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    malware_scan_status: str = Field(min_length=1)
    local_path: str | None = None
    correlation_id: str | None = None
    priority: JobPriority = JobPriority.HIGH


class JobRef(BaseModel):
    """Stable reference returned immediately after a job is accepted."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID = Field(default_factory=uuid4)
    workflow_run_id: UUID
    status: JobStatus = JobStatus.QUEUED
    priority: JobPriority = JobPriority.HIGH
    queued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowJobQueue(Protocol):
    """Boundary used by the application to publish document workflow jobs."""

    async def enqueue(self, command: DocumentProcessingCommand) -> JobRef:
        """Accept a document processing command and return its job reference."""

    async def get(self, job_id: UUID) -> JobRef | None:
        """Return the currently known job reference, when the adapter retains it."""

    async def cancel(self, job_id: UUID) -> JobRef | None:
        """Cancel a queued job; running jobs are left to their runtime policy."""

    async def cancel_for_workflow_run(self, workflow_run_id: UUID) -> JobRef | None:
        """Cancel the queued job associated with a workflow run, when supported."""

    async def get_progress(
        self,
        workflow_run_id: UUID,
    ) -> WorkflowProgressSnapshot | None:
        """Return the newest live progress snapshot for a workflow run."""


WorkflowJobHandler = Callable[[DocumentProcessingCommand], Awaitable[None]]
