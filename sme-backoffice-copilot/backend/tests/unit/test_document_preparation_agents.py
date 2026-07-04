from uuid import uuid4

import pytest

from app.providers import MockOCRProvider, ProviderRuntime
from app.providers.routing import build_default_provider_routing_config
from app.workflows import (
    DOCUMENT_INTAKE_AGENT,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    METADATA_EXTRACTOR_AGENT,
    OCR_FULL_TEXT_KEY,
    OCR_RESULT_KEY,
    PRIVACY_POLICY_GATE_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    AgentExecutionContext,
    AgentRunStatus,
    BaseAgent,
    ConfidenceLevel,
    DocumentIntakeAgent,
    DocumentLayoutAnalyzerAgent,
    HandoffType,
    PrivacyPolicyGateAgent,
    WorkflowArtifactRef,
    WorkflowStage,
    WorkflowState,
)


def create_state() -> WorkflowState:
    return WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        workflow_run_id=uuid4(),
        artifacts={
            "original": WorkflowArtifactRef(
                artifact_type="original",
                uri="local://tenants/t/documents/d/original/invoice.pdf",
                media_type="application/pdf",
                content_hash="hash-123",
            ),
        },
        policy_flags={"malware_scan_status": "not_scanned"},
    )


def create_context(state: WorkflowState) -> AgentExecutionContext:
    return AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
    )


@pytest.mark.asyncio
async def test_document_intake_agent_routes_to_privacy_gate() -> None:
    state = create_state()
    agent = DocumentIntakeAgent()

    assert isinstance(agent, BaseAgent)
    assert agent.definition.name == DOCUMENT_INTAKE_AGENT

    result = await agent.run(state=state, context=create_context(state))

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["accepted"] is True
    assert result.output["artifact_keys"] == ["original"]
    assert result.metrics == {"artifact_count": 1}
    assert len(result.handoffs) == 1

    handoff = result.handoffs[0]
    assert handoff.source_agent == DOCUMENT_INTAKE_AGENT
    assert handoff.target_agent == PRIVACY_POLICY_GATE_AGENT
    assert handoff.handoff_type == HandoffType.CONTROL
    assert handoff.stage == WorkflowStage.PRIVACY_POLICY_GATE
    assert handoff.confidence == ConfidenceLevel.HIGH
    assert "original" in handoff.payload["artifacts"]


@pytest.mark.asyncio
async def test_privacy_policy_gate_agent_routes_to_layout_analysis() -> None:
    state = create_state()
    agent = PrivacyPolicyGateAgent()

    assert isinstance(agent, BaseAgent)
    assert agent.definition.name == PRIVACY_POLICY_GATE_AGENT

    result = await agent.run(state=state, context=create_context(state))

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["policy_decision"] == "allow"
    assert result.output["policy_mode"] == "placeholder"
    assert result.output["policy_flags"] == state.policy_flags
    assert len(result.handoffs) == 1

    handoff = result.handoffs[0]
    assert handoff.source_agent == PRIVACY_POLICY_GATE_AGENT
    assert handoff.target_agent == DOCUMENT_LAYOUT_ANALYZER_AGENT
    assert handoff.stage == WorkflowStage.LAYOUT_ANALYSIS
    assert handoff.payload["policy_decision"] == "allow"


@pytest.mark.asyncio
async def test_document_layout_analyzer_agent_routes_to_extraction_agents() -> None:
    state = create_state()
    agent = DocumentLayoutAnalyzerAgent()

    assert isinstance(agent, BaseAgent)
    assert agent.definition.name == DOCUMENT_LAYOUT_ANALYZER_AGENT

    result = await agent.run(state=state, context=create_context(state))

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["layout_detected"] is False
    assert result.output["requires_ocr"] is True
    assert result.metrics == {"layout_group_count": 3}
    assert {handoff.target_agent for handoff in result.handoffs} == {
        METADATA_EXTRACTOR_AGENT,
        TABLE_EXTRACTOR_AGENT,
        TOTALS_EXTRACTOR_AGENT,
    }
    assert {handoff.stage for handoff in result.handoffs} == {
        WorkflowStage.METADATA_EXTRACTION,
        WorkflowStage.TABLE_EXTRACTION,
        WorkflowStage.TOTALS_EXTRACTION,
    }
    assert all(
        handoff.confidence == ConfidenceLevel.UNKNOWN for handoff in result.handoffs
    )
    assert all(
        handoff.payload["layout_groups"] == result.output["layout_groups"]
        for handoff in result.handoffs
    )


@pytest.mark.asyncio
async def test_document_layout_analyzer_runs_selected_ocr_provider() -> None:
    state = create_state()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        ocr_provider=MockOCRProvider(),
    )
    agent = DocumentLayoutAnalyzerAgent()

    result = await agent.run(state=state, context=context)

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["ocr_available"] is True
    assert result.output["requires_ocr"] is False
    assert result.output["ocr_provider"] == "mock_ocr"
    assert OCR_RESULT_KEY in state.scratchpad
    assert OCR_FULL_TEXT_KEY in state.scratchpad
    assert "Invoice #INV-MOCK-001" in state.scratchpad[OCR_FULL_TEXT_KEY]
    assert all(
        handoff.payload["ocr_result_ref"] == OCR_RESULT_KEY
        for handoff in result.handoffs
    )


@pytest.mark.asyncio
async def test_document_preparation_agents_fail_on_context_mismatch() -> None:
    state = create_state()
    context = AgentExecutionContext(
        tenant_id=uuid4(),
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
    )

    result = await DocumentIntakeAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.FAILED
    assert result.error_code == "ERR_WORKFLOW_CONTEXT_MISMATCH"
