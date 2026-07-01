"""Document preparation agent skeletons for the workflow entry path."""

from __future__ import annotations

from app.workflows.agents import (
    AgentDefinitionSpec,
    AgentExecutionContext,
    AgentRunResult,
    AgentRunStatus,
)
from app.workflows.contracts import (
    AgentHandoffEnvelope,
    ConfidenceLevel,
    HandoffType,
    WorkflowStage,
    WorkflowState,
)

DOCUMENT_INTAKE_AGENT = "document_intake"
PRIVACY_POLICY_GATE_AGENT = "privacy_policy_gate"
DOCUMENT_LAYOUT_ANALYZER_AGENT = "document_layout_analyzer"
METADATA_EXTRACTOR_AGENT = "metadata_extractor"
TABLE_EXTRACTOR_AGENT = "table_extractor"
TOTALS_EXTRACTOR_AGENT = "totals_extractor"


def validate_agent_context(
    *,
    state: WorkflowState,
    context: AgentExecutionContext,
    agent_name: str,
) -> AgentRunResult | None:
    """Return a failure result when execution context does not match state."""

    if context.tenant_id != state.tenant_id:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_WORKFLOW_CONTEXT_MISMATCH",
            error_message=(
                f"{agent_name} received a tenant_id that does not match state."
            ),
        )
    if context.document_id != state.document_id:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_WORKFLOW_CONTEXT_MISMATCH",
            error_message=(
                f"{agent_name} received a document_id that does not match state."
            ),
        )
    if (
        context.workflow_run_id is not None
        and state.workflow_run_id is not None
        and context.workflow_run_id != state.workflow_run_id
    ):
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_WORKFLOW_CONTEXT_MISMATCH",
            error_message=(
                f"{agent_name} received a workflow_run_id that does not match state."
            ),
        )
    return None


def summarize_artifacts(state: WorkflowState) -> dict[str, object]:
    """Return a small artifact summary safe to pass between skeleton agents."""

    summary: dict[str, object] = {}
    for artifact_key, artifact in state.artifacts.items():
        summary[artifact_key] = {
            "artifact_type": artifact.artifact_type,
            "uri": artifact.uri,
            "media_type": artifact.media_type,
            "content_hash": artifact.content_hash,
        }
    return summary


def build_control_handoff(
    *,
    state: WorkflowState,
    source_agent: str,
    target_agent: str,
    stage: WorkflowStage,
    payload: dict[str, object],
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
) -> AgentHandoffEnvelope:
    """Build a standard control handoff for document preparation agents."""

    return AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        source_agent=source_agent,
        target_agent=target_agent,
        handoff_type=HandoffType.CONTROL,
        stage=stage,
        payload=payload,
        confidence=confidence,
    )


class DocumentIntakeAgent:
    """Skeleton agent that accepts an ingested document into workflow state."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned document intake agent definition."""

        return AgentDefinitionSpec(
            name=DOCUMENT_INTAKE_AGENT,
            version="0.1.0",
            description="Loads the ingested document context for downstream agents.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="workflow-state.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Accept document context and route to the privacy/policy gate."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=DOCUMENT_INTAKE_AGENT,
        )
        if context_error is not None:
            return context_error

        artifact_summary = summarize_artifacts(state)
        output: dict[str, object] = {
            "document_id": str(state.document_id),
            "document_type": state.document_type,
            "artifact_keys": list(state.artifacts.keys()),
            "accepted": True,
        }
        next_handoff = build_control_handoff(
            state=state,
            source_agent=DOCUMENT_INTAKE_AGENT,
            target_agent=PRIVACY_POLICY_GATE_AGENT,
            stage=WorkflowStage.PRIVACY_POLICY_GATE,
            payload={
                "document_type": state.document_type,
                "artifacts": artifact_summary,
            },
        )
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[next_handoff],
            confidence=ConfidenceLevel.HIGH,
            metrics={"artifact_count": len(state.artifacts)},
        )


class PrivacyPolicyGateAgent:
    """Skeleton agent that records a placeholder policy decision."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned privacy and policy gate definition."""

        return AgentDefinitionSpec(
            name=PRIVACY_POLICY_GATE_AGENT,
            version="0.1.0",
            description="Applies placeholder privacy and policy checks.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="workflow-state.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Allow local processing and route to layout analysis."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=PRIVACY_POLICY_GATE_AGENT,
        )
        if context_error is not None:
            return context_error

        output: dict[str, object] = {
            "policy_decision": "allow",
            "policy_mode": "placeholder",
            "policy_flags": state.policy_flags,
        }
        next_handoff = build_control_handoff(
            state=state,
            source_agent=PRIVACY_POLICY_GATE_AGENT,
            target_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            stage=WorkflowStage.LAYOUT_ANALYSIS,
            payload=output,
        )
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[next_handoff],
            confidence=ConfidenceLevel.HIGH,
        )


class DocumentLayoutAnalyzerAgent:
    """Skeleton agent that defines placeholder document layout regions."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned document layout analyzer definition."""

        return AgentDefinitionSpec(
            name=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            version="0.1.0",
            description="Creates placeholder layout regions before OCR/LLM providers.",
            input_schema_ref="workflow-state.v1",
            output_schema_ref="document-layout.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Return placeholder layout groups and route to extraction agents."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=DOCUMENT_LAYOUT_ANALYZER_AGENT,
        )
        if context_error is not None:
            return context_error

        layout_groups: dict[str, object] = {
            "metadata_region": None,
            "table_region": None,
            "totals_region": None,
            "source": "placeholder",
        }
        output: dict[str, object] = {
            "layout_detected": False,
            "layout_groups": layout_groups,
            "requires_ocr": True,
        }
        extraction_payload: dict[str, object] = {
            "document_type": state.document_type,
            "layout_groups": layout_groups,
        }
        handoffs = [
            build_control_handoff(
                state=state,
                source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
                target_agent=METADATA_EXTRACTOR_AGENT,
                stage=WorkflowStage.METADATA_EXTRACTION,
                payload=extraction_payload,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
            build_control_handoff(
                state=state,
                source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
                target_agent=TABLE_EXTRACTOR_AGENT,
                stage=WorkflowStage.TABLE_EXTRACTION,
                payload=extraction_payload,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
            build_control_handoff(
                state=state,
                source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
                target_agent=TOTALS_EXTRACTOR_AGENT,
                stage=WorkflowStage.TOTALS_EXTRACTION,
                payload=extraction_payload,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
        ]
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=handoffs,
            confidence=ConfidenceLevel.UNKNOWN,
            metrics={"layout_group_count": 3},
        )
