from uuid import uuid4

from app.models.workflow import (
    AgentHandoff,
    AgentStepExecution,
    AgentStepStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.observability.metrics import metrics_registry
from app.workflows import (
    AgentHandoffEnvelope,
    AgentRunResult,
    AgentRunStatus,
    ConfidenceLevel,
    HandoffType,
    WorkflowRuntimeService,
    WorkflowStage,
    WorkflowState,
    WorkflowStateStatus,
)


class FakeWorkflowRuntimePersistence:
    def __init__(self) -> None:
        self.workflow_runs: list[WorkflowRun] = []
        self.step_executions: list[AgentStepExecution] = []
        self.handoffs: list[AgentHandoff] = []

    def add_workflow_run(self, workflow_run: WorkflowRun) -> WorkflowRun:
        self.workflow_runs.append(workflow_run)
        return workflow_run

    def add_step_execution(
        self,
        step_execution: AgentStepExecution,
    ) -> AgentStepExecution:
        self.step_executions.append(step_execution)
        return step_execution

    def add_handoff(self, handoff: AgentHandoff) -> AgentHandoff:
        self.handoffs.append(handoff)
        return handoff


def create_state(*, max_retries: int = 3) -> WorkflowState:
    return WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        max_retries=max_retries,
    )


def test_start_workflow_persists_running_workflow_state() -> None:
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state()

    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
        correlation_id="corr-123",
    )

    assert workflow_run in persistence.workflow_runs
    assert state.workflow_run_id == workflow_run.id
    assert state.status == WorkflowStateStatus.RUNNING
    assert workflow_run.status == WorkflowRunStatus.RUNNING.value
    assert workflow_run.correlation_id == "corr-123"
    assert workflow_run.state is not None
    assert workflow_run.state["status"] == WorkflowStateStatus.RUNNING.value


def test_queue_workflow_persists_a_queued_workflow_state() -> None:
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state()

    workflow_run = runtime.queue_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
        correlation_id="corr-queued",
    )

    assert workflow_run in persistence.workflow_runs
    assert state.workflow_run_id == workflow_run.id
    assert state.status == WorkflowStateStatus.QUEUED
    assert workflow_run.status == WorkflowRunStatus.QUEUED.value
    assert workflow_run.state is not None
    assert workflow_run.state["status"] == WorkflowStateStatus.QUEUED.value


def test_record_agent_step_persists_step_execution_and_updates_state() -> None:
    metrics_registry.reset()
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state()
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
    )
    result = AgentRunResult(
        status=AgentRunStatus.SUCCEEDED,
        output={"document_loaded": True},
        confidence=ConfidenceLevel.HIGH,
        metrics={"duration_ms": 12},
    )

    step = runtime.record_agent_step(
        workflow_run=workflow_run,
        state=state,
        agent_name="document_intake",
        result=result,
        input_ref="state://before/document_intake",
        output_ref="state://after/document_intake",
    )

    assert step in persistence.step_executions
    assert step.workflow_run_id == workflow_run.id
    assert step.agent_name == "document_intake"
    assert step.status == AgentStepStatus.SUCCEEDED.value
    assert step.confidence == ConfidenceLevel.HIGH.value
    assert step.metrics == {"duration_ms": 12}
    assert state.completed_agents == ["document_intake"]
    assert workflow_run.current_agent == "document_intake"
    assert workflow_run.state is not None
    assert workflow_run.state["completed_agents"] == ["document_intake"]
    snapshot = metrics_registry.snapshot()
    metric = snapshot["agent_steps"]["document_intake:succeeded"]
    assert metric["count"] == 1
    assert metric["avg_duration_ms"] == 12.0


def test_record_handoff_persists_envelope_and_updates_routing_state() -> None:
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state()
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
    )
    step = runtime.record_agent_step(
        workflow_run=workflow_run,
        state=state,
        agent_name="metadata_extractor",
        result=AgentRunResult(status=AgentRunStatus.SUCCEEDED),
    )
    envelope = AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        source_agent="metadata_extractor",
        target_agent="qa_validator",
        handoff_type=HandoffType.DATA,
        stage=WorkflowStage.QA_VALIDATION,
        payload={"invoice_number": "INV-001"},
        evidence_refs=["page:1:bbox:10,10,200,40"],
        confidence=ConfidenceLevel.HIGH,
    )

    handoff = runtime.record_handoff(
        workflow_run=workflow_run,
        state=state,
        envelope=envelope,
        source_step=step,
    )

    assert handoff in persistence.handoffs
    assert handoff.workflow_run_id == workflow_run.id
    assert handoff.source_step_execution_id == step.id
    assert handoff.source_agent == "metadata_extractor"
    assert handoff.target_agent == "qa_validator"
    assert handoff.payload_ref == f"inline://handoffs/{envelope.handoff_id}"
    assert handoff.evidence_refs == ["page:1:bbox:10,10,200,40"]
    assert handoff.confidence == ConfidenceLevel.HIGH.value
    assert state.latest_handoff == envelope
    assert state.current_agent == "qa_validator"
    assert workflow_run.current_agent == "qa_validator"


def test_request_retry_tracks_counts_and_marks_workflow_retrying() -> None:
    metrics_registry.reset()
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state(max_retries=2)
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
    )

    first_retry = runtime.request_retry(
        workflow_run=workflow_run,
        state=state,
        agent_name="totals_extractor",
    )
    second_retry = runtime.request_retry(
        workflow_run=workflow_run,
        state=state,
        agent_name="totals_extractor",
    )

    assert first_retry.retry_allowed is True
    assert second_retry.retry_allowed is True
    assert state.retry_counts == {"totals_extractor": 2}
    assert workflow_run.retry_count == 2
    assert workflow_run.status == WorkflowRunStatus.RETRYING.value
    assert state.status == WorkflowStateStatus.RETRYING
    assert workflow_run.current_agent == "totals_extractor"
    snapshot = metrics_registry.snapshot()
    assert snapshot["retry_counts"]["agent:totals_extractor"] == 2


def test_request_retry_dead_letters_after_retry_budget_is_exhausted() -> None:
    metrics_registry.reset()
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state(max_retries=1)
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
    )

    allowed_retry = runtime.request_retry(
        workflow_run=workflow_run,
        state=state,
        agent_name="qa_validator",
    )
    exhausted_retry = runtime.request_retry(
        workflow_run=workflow_run,
        state=state,
        agent_name="qa_validator",
    )

    assert allowed_retry.retry_allowed is True
    assert exhausted_retry.retry_allowed is False
    assert exhausted_retry.workflow_status == WorkflowStateStatus.DEAD_LETTERED
    assert workflow_run.status == WorkflowRunStatus.DEAD_LETTERED.value
    assert workflow_run.error_code == "RETRY_EXHAUSTED"
    assert state.status == WorkflowStateStatus.DEAD_LETTERED
    assert state.stage == WorkflowStage.FAILED
    assert workflow_run.state is not None
    assert workflow_run.state["status"] == WorkflowStateStatus.DEAD_LETTERED.value
    snapshot = metrics_registry.snapshot()
    assert snapshot["retry_counts"]["agent:qa_validator"] == 2
    assert snapshot["failure_counts"]["retry_exhausted:qa_validator"] == 1


def test_update_workflow_status_and_mark_failed_sync_durable_state() -> None:
    persistence = FakeWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_state()
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="document_processing",
        workflow_version="0.1.0",
    )

    runtime.update_workflow_status(
        workflow_run=workflow_run,
        state=state,
        status=WorkflowStateStatus.REVIEW_REQUIRED,
        stage=WorkflowStage.REVIEW_COORDINATION,
        current_agent="review_coordinator",
    )

    assert workflow_run.status == WorkflowRunStatus.REVIEW_REQUIRED.value
    assert state.stage == WorkflowStage.REVIEW_COORDINATION
    assert workflow_run.current_agent == "review_coordinator"

    runtime.mark_failed(
        workflow_run=workflow_run,
        state=state,
        error_code="ERR_WORKFLOW_FAILED",
        error_message="Workflow failed during validation.",
    )

    assert workflow_run.status == WorkflowRunStatus.FAILED.value
    assert state.status == WorkflowStateStatus.FAILED
    assert state.stage == WorkflowStage.FAILED
    assert workflow_run.error_code == "ERR_WORKFLOW_FAILED"
