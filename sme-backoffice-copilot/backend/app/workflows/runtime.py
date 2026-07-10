"""Runtime foundation for controlled multi-agent workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID, uuid4

from app.models.workflow import (
    AgentHandoff,
    AgentStepExecution,
    AgentStepStatus,
    HandoffStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.observability.metrics import metrics_registry
from app.workflows.agents import AgentRunResult, AgentRunStatus
from app.workflows.contracts import (
    AgentHandoffEnvelope,
    WorkflowStage,
    WorkflowState,
    WorkflowStateStatus,
)
from app.workflows.progress import workflow_stage_for_agent

logger = logging.getLogger("app.workflow")


class WorkflowRuntimePersistence(Protocol):
    """Persistence boundary used by the workflow runtime service."""

    def add_workflow_run(self, workflow_run: WorkflowRun) -> WorkflowRun:
        """Stage a workflow run for insertion."""

    def add_step_execution(
        self,
        step_execution: AgentStepExecution,
    ) -> AgentStepExecution:
        """Stage an agent step execution for insertion."""

    def add_handoff(self, handoff: AgentHandoff) -> AgentHandoff:
        """Stage an agent handoff for insertion."""


WorkflowProgressObserver = Callable[[WorkflowRun, WorkflowState], None]


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Decision returned after incrementing retry state."""

    agent_name: str
    retry_count: int
    max_retries: int
    retry_allowed: bool
    workflow_status: WorkflowStateStatus
    error_code: str | None = None
    error_message: str | None = None


def serialize_workflow_state(state: WorkflowState) -> dict[str, object]:
    """Return a JSON-compatible workflow state snapshot for durable storage."""

    return cast(dict[str, object], state.model_dump(mode="json"))


def workflow_status_to_model_status(status: WorkflowStateStatus) -> WorkflowRunStatus:
    """Map runtime workflow state status to durable workflow run status."""

    status_map = {
        WorkflowStateStatus.QUEUED: WorkflowRunStatus.QUEUED,
        WorkflowStateStatus.RUNNING: WorkflowRunStatus.RUNNING,
        WorkflowStateStatus.RETRYING: WorkflowRunStatus.RETRYING,
        WorkflowStateStatus.REVIEW_REQUIRED: WorkflowRunStatus.REVIEW_REQUIRED,
        WorkflowStateStatus.COMPLETED: WorkflowRunStatus.COMPLETED,
        WorkflowStateStatus.FAILED: WorkflowRunStatus.FAILED,
        WorkflowStateStatus.CANCELLED: WorkflowRunStatus.CANCELLED,
        WorkflowStateStatus.LOST: WorkflowRunStatus.LOST,
        WorkflowStateStatus.DEAD_LETTERED: WorkflowRunStatus.DEAD_LETTERED,
    }
    return status_map[status]


def agent_result_status_to_step_status(status: AgentRunStatus) -> AgentStepStatus:
    """Map normalized agent result status to durable step execution status."""

    status_map = {
        AgentRunStatus.SUCCEEDED: AgentStepStatus.SUCCEEDED,
        AgentRunStatus.FAILED: AgentStepStatus.FAILED,
        AgentRunStatus.REVIEW_REQUIRED: AgentStepStatus.REVIEW_REQUIRED,
        AgentRunStatus.RETRY_REQUESTED: AgentStepStatus.RETRYING,
        AgentRunStatus.SKIPPED: AgentStepStatus.SKIPPED,
    }
    return status_map[status]


def metric_float(value: object) -> float | None:
    """Return a numeric metric value as float."""

    if isinstance(value, int | float):
        return float(value)
    return None


class WorkflowRuntimeService:
    """Small runtime service for durable workflow bookkeeping."""

    def __init__(
        self,
        persistence: WorkflowRuntimePersistence,
        *,
        progress_observer: WorkflowProgressObserver | None = None,
    ) -> None:
        self.persistence = persistence
        self.progress_observer = progress_observer

    def start_workflow(
        self,
        *,
        state: WorkflowState,
        workflow_name: str,
        workflow_version: str,
        correlation_id: str | None = None,
    ) -> WorkflowRun:
        """Create and persist a running workflow record from a state snapshot."""

        workflow_run_id = state.workflow_run_id or uuid4()
        state.workflow_run_id = workflow_run_id
        state.status = WorkflowStateStatus.RUNNING

        workflow_run = WorkflowRun(
            id=workflow_run_id,
            tenant_id=state.tenant_id,
            document_id=state.document_id,
            processing_run_id=state.processing_run_id,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            status=WorkflowRunStatus.RUNNING.value,
            current_agent=state.current_agent,
            retry_count=sum(state.retry_counts.values()),
            correlation_id=correlation_id,
            state=serialize_workflow_state(state),
        )
        logger.info(
            "workflow.started",
            extra={
                "event": "workflow.started",
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(state.tenant_id),
                "document_id": str(state.document_id),
                "workflow_name": workflow_name,
                "workflow_version": workflow_version,
                "correlation_id": correlation_id,
            },
        )
        persisted_run = self.persistence.add_workflow_run(workflow_run)
        self._notify_progress(persisted_run, state)
        return persisted_run

    def queue_workflow(
        self,
        *,
        state: WorkflowState,
        workflow_name: str,
        workflow_version: str,
        correlation_id: str | None = None,
    ) -> WorkflowRun:
        """Persist a workflow that has been accepted but not yet started."""

        workflow_run_id = state.workflow_run_id or uuid4()
        state.workflow_run_id = workflow_run_id
        state.status = WorkflowStateStatus.QUEUED
        workflow_run = WorkflowRun(
            id=workflow_run_id,
            tenant_id=state.tenant_id,
            document_id=state.document_id,
            processing_run_id=state.processing_run_id,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            status=WorkflowRunStatus.QUEUED.value,
            current_agent=state.current_agent,
            retry_count=sum(state.retry_counts.values()),
            correlation_id=correlation_id,
            state=serialize_workflow_state(state),
        )
        logger.info(
            "workflow.queued",
            extra={
                "event": "workflow.queued",
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(state.tenant_id),
                "document_id": str(state.document_id),
                "workflow_name": workflow_name,
                "workflow_version": workflow_version,
                "correlation_id": correlation_id,
            },
        )
        persisted_run = self.persistence.add_workflow_run(workflow_run)
        self._notify_progress(persisted_run, state)
        return persisted_run

    def resume_workflow(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        correlation_id: str | None = None,
    ) -> WorkflowRun:
        """Move a previously queued workflow into the running state."""

        state.workflow_run_id = workflow_run.id
        state.status = WorkflowStateStatus.RUNNING
        workflow_run.status = WorkflowRunStatus.RUNNING.value
        workflow_run.current_agent = state.current_agent
        if correlation_id is not None:
            workflow_run.correlation_id = correlation_id
        workflow_run.state = serialize_workflow_state(state)
        logger.info(
            "workflow.resumed",
            extra={
                "event": "workflow.resumed",
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(state.tenant_id),
                "document_id": str(state.document_id),
                "correlation_id": workflow_run.correlation_id,
            },
        )
        self._notify_progress(workflow_run, state)
        return workflow_run

    def record_agent_step(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        agent_name: str,
        result: AgentRunResult,
        attempt: int = 1,
        agent_definition_id: UUID | None = None,
        input_ref: str | None = None,
        output_ref: str | None = None,
    ) -> AgentStepExecution:
        """Persist one agent step execution and sync workflow state."""

        step_status = agent_result_status_to_step_status(result.status)
        result_metrics = dict(result.metrics)
        duration_ms = metric_float(result_metrics.get("duration_ms"))
        step_execution = AgentStepExecution(
            id=uuid4(),
            tenant_id=state.tenant_id,
            workflow_run_id=workflow_run.id,
            agent_definition_id=agent_definition_id,
            agent_name=agent_name,
            status=step_status.value,
            attempt=attempt,
            input_ref=input_ref,
            output_ref=output_ref,
            confidence=result.confidence.value,
            error_code=result.error_code,
            error_message=result.error_message,
            metrics=result_metrics or None,
        )

        state.current_agent = agent_name
        workflow_run.current_agent = agent_name
        agent_stage = workflow_stage_for_agent(agent_name)
        if agent_stage is not None:
            state.stage = agent_stage

        if result.status == AgentRunStatus.SUCCEEDED:
            if agent_name not in state.completed_agents:
                state.completed_agents.append(agent_name)
        if result.status == AgentRunStatus.REVIEW_REQUIRED:
            state.status = WorkflowStateStatus.REVIEW_REQUIRED
            workflow_run.status = WorkflowRunStatus.REVIEW_REQUIRED.value
        if result.status == AgentRunStatus.FAILED:
            state.status = WorkflowStateStatus.FAILED
            state.stage = WorkflowStage.FAILED
            workflow_run.status = WorkflowRunStatus.FAILED.value
            workflow_run.error_code = result.error_code
            workflow_run.error_message = result.error_message

        workflow_run.state = serialize_workflow_state(state)
        metrics_registry.record_agent_step(
            agent_name=agent_name,
            status=step_status.value,
            duration_ms=duration_ms,
            attempt=attempt,
        )
        logger.info(
            "workflow.agent_step.recorded",
            extra={
                "event": "workflow.agent_step.recorded",
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(state.tenant_id),
                "document_id": str(state.document_id),
                "agent_name": agent_name,
                "status": step_status.value,
                "attempt": attempt,
                "correlation_id": workflow_run.correlation_id,
            },
        )
        persisted_step = self.persistence.add_step_execution(step_execution)
        self._notify_progress(workflow_run, state)
        return persisted_step

    def record_handoff(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        envelope: AgentHandoffEnvelope,
        source_step: AgentStepExecution | None = None,
    ) -> AgentHandoff:
        """Persist one agent handoff and sync routing state."""

        if envelope.tenant_id != state.tenant_id:
            raise ValueError("Handoff tenant_id does not match workflow state.")
        if envelope.document_id != state.document_id:
            raise ValueError("Handoff document_id does not match workflow state.")

        handoff = AgentHandoff(
            id=envelope.handoff_id,
            tenant_id=envelope.tenant_id,
            workflow_run_id=workflow_run.id,
            source_step_execution_id=source_step.id
            if source_step is not None
            else None,
            source_agent=envelope.source_agent,
            target_agent=envelope.target_agent,
            handoff_type=envelope.handoff_type.value,
            schema_version=envelope.schema_version,
            status=HandoffStatus.CREATED.value,
            payload_ref=envelope.payload_ref
            or f"inline://handoffs/{envelope.handoff_id}",
            evidence_refs=envelope.evidence_refs or None,
            confidence=envelope.confidence.value,
            validation_status=(
                envelope.qa_error_signal.severity.value
                if envelope.qa_error_signal is not None
                else None
            ),
            policy_flags=envelope.policy_flags or None,
            attempt=envelope.attempt,
        )

        state.latest_handoff = envelope
        state.stage = envelope.stage
        state.current_agent = envelope.target_agent
        workflow_run.current_agent = envelope.target_agent
        workflow_run.state = serialize_workflow_state(state)
        return self.persistence.add_handoff(handoff)

    def update_workflow_status(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        status: WorkflowStateStatus,
        stage: WorkflowStage | None = None,
        current_agent: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> WorkflowRun:
        """Update durable workflow status and state snapshot together."""

        state.status = status
        if stage is not None:
            state.stage = stage
        elif status == WorkflowStateStatus.COMPLETED:
            state.stage = WorkflowStage.COMPLETED
        elif status in {
            WorkflowStateStatus.FAILED,
            WorkflowStateStatus.LOST,
            WorkflowStateStatus.DEAD_LETTERED,
        }:
            state.stage = WorkflowStage.FAILED

        if current_agent is not None:
            state.current_agent = current_agent

        workflow_run.status = workflow_status_to_model_status(status).value
        workflow_run.current_agent = state.current_agent
        workflow_run.error_code = error_code
        workflow_run.error_message = error_message
        workflow_run.state = serialize_workflow_state(state)
        logger.info(
            "workflow.status.updated",
            extra={
                "event": "workflow.status.updated",
                "workflow_run_id": str(workflow_run.id),
                "tenant_id": str(state.tenant_id),
                "document_id": str(state.document_id),
                "status": workflow_run.status,
                "stage": state.stage.value,
                "current_agent": workflow_run.current_agent,
                "error_code": error_code,
                "correlation_id": workflow_run.correlation_id,
            },
        )
        self._notify_progress(workflow_run, state)
        return workflow_run

    def request_retry(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        agent_name: str,
        error_code: str = "RETRY_EXHAUSTED",
        error_message: str | None = None,
    ) -> RetryDecision:
        """Increment retry counters and dead-letter when retry budget is exhausted."""

        retry_count = state.retry_counts.get(agent_name, 0) + 1
        state.retry_counts[agent_name] = retry_count
        workflow_run.retry_count += 1

        if retry_count > state.max_retries:
            resolved_message = (
                error_message or f"Retry budget exhausted for agent '{agent_name}'."
            )
            self.mark_failed(
                workflow_run=workflow_run,
                state=state,
                error_code=error_code,
                error_message=resolved_message,
                dead_letter=True,
            )
            decision = RetryDecision(
                agent_name=agent_name,
                retry_count=retry_count,
                max_retries=state.max_retries,
                retry_allowed=False,
                workflow_status=WorkflowStateStatus.DEAD_LETTERED,
                error_code=error_code,
                error_message=resolved_message,
            )
            metrics_registry.record_workflow_retry(
                agent_name=agent_name,
                retry_allowed=decision.retry_allowed,
            )
            return decision

        self.update_workflow_status(
            workflow_run=workflow_run,
            state=state,
            status=WorkflowStateStatus.RETRYING,
            current_agent=agent_name,
        )
        decision = RetryDecision(
            agent_name=agent_name,
            retry_count=retry_count,
            max_retries=state.max_retries,
            retry_allowed=True,
            workflow_status=WorkflowStateStatus.RETRYING,
        )
        metrics_registry.record_workflow_retry(
            agent_name=agent_name,
            retry_allowed=decision.retry_allowed,
        )
        return decision

    def mark_failed(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        error_code: str,
        error_message: str,
        dead_letter: bool = False,
    ) -> WorkflowRun:
        """Move a workflow into failed or dead-lettered terminal state."""

        status = (
            WorkflowStateStatus.DEAD_LETTERED
            if dead_letter
            else WorkflowStateStatus.FAILED
        )
        return self.update_workflow_status(
            workflow_run=workflow_run,
            state=state,
            status=status,
            stage=WorkflowStage.FAILED,
            error_code=error_code,
            error_message=error_message,
        )

    def _notify_progress(
        self,
        workflow_run: WorkflowRun,
        state: WorkflowState,
    ) -> None:
        """Publish an in-process snapshot without coupling runtime to a queue."""

        if self.progress_observer is not None:
            self.progress_observer(workflow_run, state)
