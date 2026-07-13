"""Read models for durable workflow execution state."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.workflow import WorkflowRun
from app.workflows.contracts import WorkflowState
from app.workflows.progress import WorkflowProgressSnapshot, build_workflow_progress


class WorkflowProgressResponse(BaseModel):
    """Workflow phase data used by the upload status UI."""

    phase: str
    label: str
    percent: int
    current_agent: str | None
    completed_agents: list[str]
    is_terminal: bool

    @classmethod
    def from_snapshot(
        cls,
        snapshot: WorkflowProgressSnapshot,
    ) -> "WorkflowProgressResponse":
        return cls(
            phase=snapshot.phase,
            label=snapshot.label,
            percent=snapshot.percent,
            current_agent=snapshot.current_agent,
            completed_agents=snapshot.completed_agents,
            is_terminal=snapshot.is_terminal,
        )


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
    progress: WorkflowProgressResponse

    @classmethod
    def from_model(
        cls,
        workflow_run: WorkflowRun,
        *,
        live_progress: WorkflowProgressSnapshot | None = None,
    ) -> "WorkflowRunStatusResponse":
        state = workflow_run.state or {}
        durable_state = WorkflowState.model_validate(
            {
                "tenant_id": workflow_run.tenant_id,
                "document_id": workflow_run.document_id,
                "document_type": "other",
                "workflow_run_id": workflow_run.id,
                "status": workflow_run.status,
                "current_agent": workflow_run.current_agent,
                **state,
            }
        )
        progress = build_workflow_progress(durable_state)
        if live_progress is not None and not progress.is_terminal:
            progress = live_progress
        return cls(
            id=workflow_run.id,
            document_id=workflow_run.document_id,
            workflow_name=workflow_run.workflow_name,
            workflow_version=workflow_run.workflow_version,
            status=progress.status,
            stage=progress.stage,
            current_agent=progress.current_agent,
            retry_count=workflow_run.retry_count or 0,
            correlation_id=workflow_run.correlation_id,
            error_code=workflow_run.error_code,
            error_message=workflow_run.error_message,
            created_at=workflow_run.created_at,
            updated_at=workflow_run.updated_at,
            progress=WorkflowProgressResponse.from_snapshot(progress),
        )
