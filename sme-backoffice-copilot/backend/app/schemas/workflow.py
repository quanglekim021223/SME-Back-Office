"""Read models for durable workflow execution state."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.workflow import WorkflowRun


class WorkflowRunStatusResponse(BaseModel):
    """Tenant-scoped workflow state suitable for polling by a client."""

    id: UUID
    document_id: UUID | None
    workflow_name: str
    workflow_version: str
    status: str
    stage: str | None
    current_agent: str | None
    retry_count: int
    correlation_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, workflow_run: WorkflowRun) -> "WorkflowRunStatusResponse":
        state = workflow_run.state or {}
        stage = state.get("stage")
        return cls(
            id=workflow_run.id,
            document_id=workflow_run.document_id,
            workflow_name=workflow_run.workflow_name,
            workflow_version=workflow_run.workflow_version,
            status=workflow_run.status,
            stage=stage if isinstance(stage, str) else None,
            current_agent=workflow_run.current_agent,
            retry_count=workflow_run.retry_count,
            correlation_id=workflow_run.correlation_id,
            error_code=workflow_run.error_code,
            error_message=workflow_run.error_message,
            created_at=workflow_run.created_at,
            updated_at=workflow_run.updated_at,
        )
