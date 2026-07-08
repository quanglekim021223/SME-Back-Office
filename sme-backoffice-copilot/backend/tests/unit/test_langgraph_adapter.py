"""Tests for the LangGraph workflow adapter."""

from __future__ import annotations

import pytest

from app.models.workflow import WorkflowRun
from app.observability.tracing import InMemoryTraceProvider
from app.workflows.agents import AgentExecutionContext
from app.workflows.contracts import WorkflowState, WorkflowStateStatus
from app.workflows.document_preparation import (
    DOCUMENT_INTAKE_AGENT,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    METADATA_EXTRACTOR_AGENT,
    PRIVACY_POLICY_GATE_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
)
from app.workflows.invoice_extraction import (
    CLASSIFICATION_AGENT,
    INVOICE_ASSEMBLY_NODE,
    QA_VALIDATION_AGENT,
    create_total_amount_correction_signal,
)
from app.workflows.langgraph_adapter import (
    LANGGRAPH_RETRY_GATE_NODE,
    LangGraphWorkflowAdapter,
    is_langgraph_available,
)
from app.workflows.replay import (
    InMemoryWorkflowRuntimePersistence,
    WorkflowReplayRunner,
    create_replay_state,
)
from app.workflows.runtime import WorkflowRuntimeService


def _build_runtime_context(
    *,
    max_retries: int | None = None,
) -> tuple[
    InMemoryWorkflowRuntimePersistence,
    WorkflowRuntimeService,
    WorkflowState,
    WorkflowRun,
]:
    persistence = InMemoryWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_replay_state()
    if max_retries is not None:
        state.max_retries = max_retries
    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name="langgraph_document_preparation_test",
        workflow_version="0.1.0",
        correlation_id="test-langgraph-adapter",
    )
    return persistence, runtime, state, workflow_run


@pytest.mark.asyncio
async def test_document_preparation_adapter_preserves_runtime_persistence() -> None:
    """Adapter nodes should persist agent steps and handoffs via existing runtime."""

    persistence, runtime, state, workflow_run = _build_runtime_context()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        max_retries=state.max_retries,
    )

    result = await LangGraphWorkflowAdapter(runtime).run_document_preparation(
        state=state,
        workflow_run=workflow_run,
        context=context,
    )

    assert [step.agent_name for step in result.step_executions] == [
        DOCUMENT_INTAKE_AGENT,
        PRIVACY_POLICY_GATE_AGENT,
        DOCUMENT_LAYOUT_ANALYZER_AGENT,
    ]
    assert persistence.step_executions == result.step_executions
    assert persistence.handoffs == result.handoffs
    assert len(result.handoffs) == 5
    assert {handoff.target_agent for handoff in result.handoffs} == {
        PRIVACY_POLICY_GATE_AGENT,
        DOCUMENT_LAYOUT_ANALYZER_AGENT,
        METADATA_EXTRACTOR_AGENT,
        TABLE_EXTRACTOR_AGENT,
        TOTALS_EXTRACTOR_AGENT,
    }


@pytest.mark.asyncio
async def test_document_preparation_adapter_can_require_langgraph_dependency() -> None:
    """Strict graph mode should fail loudly when the dependency is missing."""

    if is_langgraph_available():
        pytest.skip("LangGraph is installed in this environment.")

    _, runtime, state, workflow_run = _build_runtime_context()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        max_retries=state.max_retries,
    )

    with pytest.raises(RuntimeError, match="LangGraph is not installed"):
        await LangGraphWorkflowAdapter(runtime).run_document_preparation(
            state=state,
            workflow_run=workflow_run,
            context=context,
            require_langgraph=True,
        )


@pytest.mark.asyncio
async def test_invoice_extraction_adapter_runs_through_qa_valid_path() -> None:
    """Invoice graph should run extraction groups, assembly, and QA."""

    persistence, runtime, state, workflow_run = _build_runtime_context()
    replay_runner = WorkflowReplayRunner()
    trace_provider = InMemoryTraceProvider()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        max_retries=state.max_retries,
        provider_runtime=replay_runner.provider_runtime,
        llm_provider=replay_runner.llm_provider,
        ocr_provider=replay_runner.ocr_provider,
        trace_provider=trace_provider,
    )

    result = await LangGraphWorkflowAdapter(runtime).run_invoice_extraction_until_qa(
        state=state,
        workflow_run=workflow_run,
        context=context,
    )

    assert [step.agent_name for step in result.step_executions] == [
        DOCUMENT_INTAKE_AGENT,
        PRIVACY_POLICY_GATE_AGENT,
        DOCUMENT_LAYOUT_ANALYZER_AGENT,
        METADATA_EXTRACTOR_AGENT,
        TABLE_EXTRACTOR_AGENT,
        TOTALS_EXTRACTOR_AGENT,
        INVOICE_ASSEMBLY_NODE,
        QA_VALIDATION_AGENT,
    ]
    assert persistence.step_executions == result.step_executions
    assert persistence.handoffs == result.handoffs
    assert result.handoffs[-1].source_agent == QA_VALIDATION_AGENT
    assert result.handoffs[-1].target_agent == CLASSIFICATION_AGENT
    event_names = [event.name for event in trace_provider.events]
    assert "ocr.call.finished" in event_names
    assert event_names.count("llm.call.finished") == 3
    assert "deterministic_validators.finished" in event_names
    assert "qa.error_signals.built" in event_names
    assert "qa.validation_passed" in event_names


@pytest.mark.asyncio
async def test_invoice_extraction_adapter_routes_targeted_qa_retry_path() -> None:
    """QA retry handoffs should rerun the targeted extractor before exhaustion."""

    persistence, runtime, state, workflow_run = _build_runtime_context(max_retries=1)
    state.qa_error_signals.append(
        create_total_amount_correction_signal(
            expected_value="110.00",
            observed_value="120.00",
            evidence_refs=["test:evidence"],
        )
    )
    replay_runner = WorkflowReplayRunner()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        max_retries=state.max_retries,
        provider_runtime=replay_runner.provider_runtime,
        llm_provider=replay_runner.llm_provider,
        ocr_provider=replay_runner.ocr_provider,
    )

    result = await LangGraphWorkflowAdapter(runtime).run_invoice_extraction_until_qa(
        state=state,
        workflow_run=workflow_run,
        context=context,
    )

    agent_names = [step.agent_name for step in result.step_executions]
    assert agent_names.count(TOTALS_EXTRACTOR_AGENT) == 2
    assert agent_names.count(INVOICE_ASSEMBLY_NODE) == 2
    assert agent_names.count(QA_VALIDATION_AGENT) == 2
    assert persistence.handoffs == result.handoffs
    assert result.handoffs[-1].source_agent == QA_VALIDATION_AGENT
    assert result.handoffs[-1].target_agent == TOTALS_EXTRACTOR_AGENT
    assert result.retry_decisions[0].retry_allowed is True
    assert result.retry_decisions[-1].retry_allowed is False
    assert state.status == WorkflowStateStatus.DEAD_LETTERED
    assert result.checkpoints[-1]["label"] == LANGGRAPH_RETRY_GATE_NODE
