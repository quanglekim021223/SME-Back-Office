"""Build tenant-scoped workflow lineage responses from durable runtime data."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from app.models.operations import AuditEvent
from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.schemas.lineage import (
    LineageAuditEvent,
    LineageCorrectionSignal,
    LineageHandoff,
    LineageStep,
    WorkflowLineageResponse,
)


class WorkflowLineageNotFoundError(LookupError):
    """No workflow lineage exists for the tenant-owned document."""


class WorkflowLineagePersistence(Protocol):
    """Minimal persistence contract required by the lineage service."""

    async def get_latest_for_document(
        self, *, tenant_id: UUID, document_id: UUID
    ) -> WorkflowRun | None: ...

    async def list_steps_for_run(
        self, *, tenant_id: UUID, workflow_run_id: UUID
    ) -> list[AgentStepExecution]: ...

    async def list_handoffs_for_run(
        self, *, tenant_id: UUID, workflow_run_id: UUID
    ) -> list[AgentHandoff]: ...

    async def list_review_audit_events_for_document(
        self, *, tenant_id: UUID, document_id: UUID, workflow_run_id: UUID
    ) -> list[AuditEvent]: ...


class WorkflowLineageService:
    """Assemble one document's latest execution graph for the API and UI."""

    def __init__(self, repository: WorkflowLineagePersistence) -> None:
        self.repository = repository

    async def get_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> WorkflowLineageResponse:
        workflow_run = await self.repository.get_latest_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        if workflow_run is None:
            raise WorkflowLineageNotFoundError

        steps = await self.repository.list_steps_for_run(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run.id,
        )
        handoffs = await self.repository.list_handoffs_for_run(
            tenant_id=tenant_id,
            workflow_run_id=workflow_run.id,
        )
        audit_events = await self.repository.list_review_audit_events_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
            workflow_run_id=workflow_run.id,
        )

        signals = _correction_signals(workflow_run.state)
        signal_by_handoff_id = _match_signals_to_handoffs(
            signals=signals,
            handoffs=handoffs,
        )
        signal_by_step_id = {
            handoff.source_step_execution_id: signal_by_handoff_id[handoff.id]
            for handoff in handoffs
            if handoff.source_step_execution_id is not None
            and handoff.id in signal_by_handoff_id
        }

        lineage_steps = [
            _step_response(
                step=step,
                step_index=index,
                correction_signal=signal_by_step_id.get(step.id),
            )
            for index, step in enumerate(steps, start=1)
        ]
        total_latency_ms = sum(step.duration_ms or 0 for step in lineage_steps)
        if total_latency_ms == 0:
            total_latency_ms = max(
                0.0,
                (workflow_run.updated_at - workflow_run.created_at).total_seconds()
                * 1000,
            )

        return WorkflowLineageResponse(
            document_id=document_id,
            workflow_run_id=workflow_run.id,
            workflow_name=workflow_run.workflow_name,
            workflow_version=workflow_run.workflow_version,
            status=workflow_run.status,
            stage=_state_value(workflow_run.state, "stage"),
            total_latency_ms=round(total_latency_ms, 2),
            workflow_state=_compact_workflow_state(workflow_run.state),
            steps=lineage_steps,
            handoffs=[
                LineageHandoff(
                    handoff_id=handoff.id,
                    source_agent=handoff.source_agent,
                    target_agent=handoff.target_agent,
                    handoff_type=handoff.handoff_type,
                    status=handoff.status,
                    attempt=handoff.attempt,
                    confidence=handoff.confidence,
                    occurred_at=handoff.created_at,
                    correction_signal=signal_by_handoff_id.get(handoff.id),
                )
                for handoff in handoffs
            ],
            audit_history=[_audit_response(event) for event in audit_events],
        )


def _step_response(
    *,
    step: AgentStepExecution,
    step_index: int,
    correction_signal: LineageCorrectionSignal | None,
) -> LineageStep:
    metrics = dict(step.metrics or {})
    duration_ms = _float_value(metrics.get("duration_ms"))
    if duration_ms is None:
        duration_ms = max(
            0.0,
            (step.updated_at - step.created_at).total_seconds() * 1000,
        )
    return LineageStep(
        step_index=step_index,
        step_execution_id=step.id,
        agent_name=step.agent_name,
        status=step.status,
        attempt=step.attempt,
        started_at=step.created_at,
        finished_at=step.updated_at,
        duration_ms=round(duration_ms, 2),
        confidence=step.confidence,
        metrics=metrics,
        error_code=step.error_code,
        error_message=step.error_message,
        correction_signal=correction_signal,
    )


def _correction_signals(
    state: dict[str, object] | None,
) -> list[LineageCorrectionSignal]:
    if not isinstance(state, dict):
        return []
    raw_signals = state.get("qa_error_signals")
    if not isinstance(raw_signals, list):
        return []

    signals: list[LineageCorrectionSignal] = []
    for raw_signal in raw_signals:
        if not isinstance(raw_signal, dict):
            continue
        raw_target = raw_signal.get("correction_target")
        if not isinstance(raw_target, dict):
            continue
        code = raw_signal.get("code")
        target_agent = raw_target.get("target_agent")
        message = raw_signal.get("message")
        if not all(
            isinstance(value, str) and value for value in (code, target_agent, message)
        ):
            continue
        signals.append(
            LineageCorrectionSignal(
                code=code,
                target_agent=target_agent,
                message=message,
                field_path=_optional_string(raw_target.get("field_path")),
                instruction=_optional_string(raw_target.get("instruction")),
                retryable=raw_signal.get("retryable") is not False,
            )
        )
    return signals


def _match_signals_to_handoffs(
    *,
    signals: Sequence[LineageCorrectionSignal],
    handoffs: Sequence[AgentHandoff],
) -> dict[UUID, LineageCorrectionSignal]:
    remaining = list(signals)
    matched: dict[UUID, LineageCorrectionSignal] = {}
    for handoff in handoffs:
        if handoff.handoff_type != "correction":
            continue
        match_index = next(
            (
                index
                for index, signal in enumerate(remaining)
                if signal.target_agent == handoff.target_agent
            ),
            None,
        )
        if match_index is not None:
            matched[handoff.id] = remaining.pop(match_index)
    return matched


def _audit_response(event: AuditEvent) -> LineageAuditEvent:
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    actor_name = _optional_string(metadata.get("actor_subject"))
    if event.actor_user is not None:
        actor_name = event.actor_user.display_name or event.actor_user.email
    return LineageAuditEvent(
        audit_event_id=event.id,
        action=event.action,
        actor_type=event.actor_type,
        actor_id=str(event.actor_user_id) if event.actor_user_id is not None else None,
        actor_name=actor_name,
        occurred_at=event.occurred_at,
        comment=_optional_string(metadata.get("comment")),
        reason_code=_optional_string(metadata.get("reason_code")),
    )


def _compact_workflow_state(state: dict[str, object] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    allowed_keys = (
        "schema_version",
        "status",
        "stage",
        "current_agent",
        "completed_agents",
        "retry_counts",
        "max_retries",
        "policy_flags",
    )
    return {key: state[key] for key in allowed_keys if key in state}


def _state_value(state: dict[str, object] | None, key: str) -> str | None:
    if not isinstance(state, dict):
        return None
    return _optional_string(state.get(key))


def _float_value(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(0.0, float(value))
    return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
