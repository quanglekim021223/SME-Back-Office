from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.workflows import (
    AgentDefinitionSpec,
    AgentExecutionContext,
    AgentHandoffEnvelope,
    AgentRunResult,
    AgentRunStatus,
    BaseAgent,
    ConfidenceLevel,
    CorrectionAction,
    HandoffType,
    QACorrectionTarget,
    QAErrorSeverity,
    QAErrorSignal,
    ToolCall,
    ToolDefinitionSpec,
    ToolExecutionContext,
    ToolResult,
    ToolRunStatus,
    WorkflowArtifactRef,
    WorkflowStage,
    WorkflowState,
    WorkflowStateStatus,
    WorkflowTool,
)


def test_workflow_state_defaults_are_isolated_and_serializable() -> None:
    tenant_id = uuid4()
    document_id = uuid4()
    state = WorkflowState(
        tenant_id=tenant_id,
        document_id=document_id,
        document_type="invoice",
    )
    other_state = WorkflowState(
        tenant_id=tenant_id,
        document_id=uuid4(),
        document_type="invoice",
    )

    state.artifacts["original"] = WorkflowArtifactRef(
        artifact_type="original",
        uri="local://tenants/t/documents/d/original/invoice.pdf",
        media_type="application/pdf",
    )

    assert state.schema_version == "workflow-state.v1"
    assert state.status == WorkflowStateStatus.QUEUED
    assert state.stage == WorkflowStage.INGESTED
    assert "original" in state.artifacts
    assert other_state.artifacts == {}

    payload = state.model_dump(mode="json")
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["document_id"] == str(document_id)
    assert payload["artifacts"]["original"]["artifact_type"] == "original"


def test_agent_handoff_envelope_carries_routing_payload_and_evidence() -> None:
    handoff = AgentHandoffEnvelope(
        tenant_id=uuid4(),
        document_id=uuid4(),
        source_agent="metadata_extractor",
        target_agent="qa_validator",
        handoff_type=HandoffType.DATA,
        stage=WorkflowStage.QA_VALIDATION,
        payload={"invoice_number": "INV-001"},
        evidence_refs=["page:1:bbox:10,10,200,40"],
        confidence=ConfidenceLevel.HIGH,
    )

    assert handoff.schema_version == "agent-handoff.v1"
    assert handoff.source_agent == "metadata_extractor"
    assert handoff.target_agent == "qa_validator"
    assert handoff.payload["invoice_number"] == "INV-001"
    assert handoff.evidence_refs == ["page:1:bbox:10,10,200,40"]


def test_qa_error_signal_targets_specific_agent_and_field() -> None:
    correction_target = QACorrectionTarget(
        target_agent="totals_extractor",
        action=CorrectionAction.RE_EXTRACT_FIELD,
        field_path="invoice.total_amount",
        evidence_refs=["page:1:bbox:300,700,520,760"],
        instruction="Re-check only the total_amount field.",
    )

    signal = QAErrorSignal(
        code="ERR_LOGIC_MATH",
        severity=QAErrorSeverity.ERROR,
        message="Extracted invoice total does not match subtotal plus tax.",
        source_agent="qa_validator",
        correction_target=correction_target,
        expected_value="11000.00",
        observed_value="12000.00",
        context={"subtotal": "10000.00", "tax": "1000.00"},
    )

    assert signal.retryable is True
    assert signal.correction_target is not None
    assert signal.correction_target.target_agent == "totals_extractor"
    assert signal.correction_target.field_path == "invoice.total_amount"
    assert signal.model_dump(mode="json")["code"] == "ERR_LOGIC_MATH"


def test_qa_error_signal_rejects_unstructured_error_codes() -> None:
    with pytest.raises(ValidationError):
        QAErrorSignal(
            code="not structured",
            severity=QAErrorSeverity.ERROR,
            message="Invalid code format.",
            source_agent="qa_validator",
        )


@pytest.mark.asyncio
async def test_base_agent_interface_contract() -> None:
    class FakeAgent:
        @property
        def definition(self) -> AgentDefinitionSpec:
            return AgentDefinitionSpec(
                name="document_intake",
                version="0.1.0",
                output_schema_ref="workflow-state.v1",
            )

        async def run(
            self,
            *,
            state: WorkflowState,
            context: AgentExecutionContext,
            handoff: AgentHandoffEnvelope | None = None,
        ) -> AgentRunResult:
            del state, context, handoff
            return AgentRunResult(
                status=AgentRunStatus.SUCCEEDED,
                output={"accepted": True},
                confidence=ConfidenceLevel.HIGH,
            )

    agent = FakeAgent()
    state = WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
    )
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
    )

    assert isinstance(agent, BaseAgent)
    result = await agent.run(state=state, context=context)
    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output == {"accepted": True}


@pytest.mark.asyncio
async def test_tool_interface_convention() -> None:
    class FakeTool:
        @property
        def definition(self) -> ToolDefinitionSpec:
            return ToolDefinitionSpec(
                name="arithmetic_validator",
                version="0.1.0",
                is_deterministic=True,
            )

        async def execute(
            self,
            *,
            call: ToolCall,
            context: ToolExecutionContext,
        ) -> ToolResult:
            del context
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolRunStatus.SUCCEEDED,
                result={"valid": True},
            )

    tool = FakeTool()
    call = ToolCall(
        tool_name="arithmetic_validator",
        arguments={"subtotal": "10000.00", "tax": "1000.00", "total": "11000.00"},
    )
    context = ToolExecutionContext(
        tenant_id=uuid4(),
        document_id=uuid4(),
        agent_name="qa_validator",
    )

    assert isinstance(tool, WorkflowTool)
    result = await tool.execute(call=call, context=context)
    assert result.status == ToolRunStatus.SUCCEEDED
    assert result.result == {"valid": True}
