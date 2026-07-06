"""Tests for the LangGraph workflow adapter."""

from __future__ import annotations

import pytest

from app.models.workflow import WorkflowRun
from app.workflows.agents import AgentExecutionContext
from app.workflows.contracts import WorkflowState
from app.workflows.document_preparation import (
    DOCUMENT_INTAKE_AGENT,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    METADATA_EXTRACTOR_AGENT,
    PRIVACY_POLICY_GATE_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
)
from app.workflows.langgraph_adapter import (
    LangGraphWorkflowAdapter,
    is_langgraph_available,
)
from app.workflows.replay import InMemoryWorkflowRuntimePersistence, create_replay_state
from app.workflows.runtime import WorkflowRuntimeService


def _build_runtime_context() -> tuple[
    InMemoryWorkflowRuntimePersistence,
    WorkflowRuntimeService,
    WorkflowState,
    WorkflowRun,
]:
    persistence = InMemoryWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = create_replay_state()
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
