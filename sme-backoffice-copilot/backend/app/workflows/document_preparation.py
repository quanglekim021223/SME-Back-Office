"""Document preparation agent skeletons for the workflow entry path."""

from __future__ import annotations

from typing import cast

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

OCR_RESULT_KEY = "ocr_result"
OCR_FULL_TEXT_KEY = "ocr_full_text"
OCR_LAYOUT_BLOCKS_KEY = "ocr_layout_blocks"
OCR_LAYOUT_DIAGNOSTICS_KEY = "ocr_layout_diagnostics"


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


def original_artifact_input(state: WorkflowState) -> object | None:
    """Build OCR input from the original workflow artifact when available."""

    from app.providers.ocr import OCRInput

    artifact = state.artifacts.get("original")
    if artifact is None:
        return None

    local_path = artifact.metadata.get("local_path")
    return OCRInput(
        artifact_uri=artifact.uri,
        media_type=artifact.media_type,
        content_hash=artifact.content_hash,
        local_path=local_path if isinstance(local_path, str) else None,
        metadata=artifact.metadata,
    )


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

        provider_output = await run_ocr_provider_if_available(
            state=state,
            context=context,
        )
        if isinstance(provider_output, AgentRunResult):
            return provider_output

        layout_groups: dict[str, object] = {
            "metadata_region": None,
            "table_region": None,
            "totals_region": None,
            "source": "ocr_provider" if provider_output is not None else "placeholder",
        }
        output: dict[str, object] = {
            "layout_detected": False,
            "layout_groups": layout_groups,
            "requires_ocr": provider_output is None,
            "ocr_available": provider_output is not None,
        }
        if provider_output is not None:
            output["ocr_provider"] = provider_output["provider_name"]
            output["ocr_text_chars"] = provider_output["full_text_length"]
            output["ocr_layout_diagnostics"] = provider_output[
                OCR_LAYOUT_DIAGNOSTICS_KEY
            ]
        extraction_payload: dict[str, object] = {
            "document_type": state.document_type,
            "layout_groups": layout_groups,
            "ocr_result_ref": OCR_RESULT_KEY if provider_output is not None else None,
            "ocr_text_ref": OCR_FULL_TEXT_KEY if provider_output is not None else None,
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
            confidence=(
                ConfidenceLevel.MEDIUM
                if provider_output is not None
                else ConfidenceLevel.UNKNOWN
            ),
            metrics={"layout_group_count": 3},
        )


async def run_ocr_provider_if_available(
    *,
    state: WorkflowState,
    context: AgentExecutionContext,
) -> dict[str, object] | AgentRunResult | None:
    """Run the selected OCR provider and store normalized OCR state when wired."""

    from app.providers.errors import ProviderError
    from app.providers.ocr import OCRProviderRunContext
    from app.providers.routing import ProviderTaskType

    if context.provider_runtime is None or context.ocr_provider is None:
        return None

    input_data = original_artifact_input(state)
    if input_data is None:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_OCR_INPUT_MISSING",
            error_message="Document layout analysis requires an original artifact.",
        )

    try:
        invocation = await context.provider_runtime.extract_ocr(
            provider=context.ocr_provider,
            task_type=ProviderTaskType.DOCUMENT_OCR,
            input_data=input_data,
            context=OCRProviderRunContext(
                tenant_id=context.tenant_id,
                document_id=context.document_id,
                workflow_run_id=context.workflow_run_id,
                correlation_id=context.correlation_id,
            ),
            privacy_context=context.provider_privacy_context,
        )
    except ProviderError as exc:
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_OCR_PROVIDER_FAILED",
            error_message=str(exc),
        )

    ocr_result_payload = cast(
        dict[str, object],
        invocation.result.model_dump(mode="json"),
    )
    layout_blocks = build_ocr_layout_blocks(ocr_result_payload)
    layout_diagnostics = build_ocr_layout_diagnostics(
        provider_name=invocation.result.provider_name,
        full_text=invocation.result.full_text,
        layout_blocks=layout_blocks,
        provider_metadata=invocation.result.metadata,
    )
    state.scratchpad[OCR_RESULT_KEY] = ocr_result_payload
    state.scratchpad[OCR_FULL_TEXT_KEY] = invocation.result.full_text
    state.scratchpad[OCR_LAYOUT_BLOCKS_KEY] = layout_blocks
    state.scratchpad[OCR_LAYOUT_DIAGNOSTICS_KEY] = layout_diagnostics
    return {
        "provider_name": invocation.result.provider_name,
        "full_text_length": len(invocation.result.full_text),
        "text_block_count": len(invocation.result.text_blocks),
        OCR_LAYOUT_DIAGNOSTICS_KEY: layout_diagnostics,
    }


def build_ocr_layout_blocks(
    ocr_result_payload: dict[str, object],
) -> list[dict[str, object]]:
    """Return provider-neutral OCR layout blocks for workflow diagnostics."""

    raw_blocks = ocr_result_payload.get("text_blocks")
    if not isinstance(raw_blocks, list):
        return []

    blocks: list[dict[str, object]] = []
    for index, raw_block in enumerate(raw_blocks, start=1):
        if not isinstance(raw_block, dict):
            continue
        text = raw_block.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        page_number = raw_block.get("page_number")
        bounding_box = raw_block.get("bounding_box")
        confidence = raw_block.get("confidence")
        blocks.append(
            {
                "id": f"ocr:block:{index}",
                "text": text,
                "page_number": page_number if isinstance(page_number, int) else 1,
                "bounding_box": (
                    bounding_box if isinstance(bounding_box, list) else None
                ),
                "confidence": confidence
                if isinstance(confidence, int | float)
                else None,
                "metadata": raw_block.get("metadata")
                if isinstance(raw_block.get("metadata"), dict)
                else {},
            }
        )
    return blocks


def build_ocr_layout_diagnostics(
    *,
    provider_name: str,
    full_text: str,
    layout_blocks: list[dict[str, object]],
    provider_metadata: dict[str, object],
) -> dict[str, object]:
    """Summarize OCR layout quality without storing huge provider payloads."""

    blocks_with_bbox = [
        block for block in layout_blocks if isinstance(block.get("bounding_box"), list)
    ]
    blocks_with_confidence = [
        block
        for block in layout_blocks
        if isinstance(block.get("confidence"), int | float)
    ]
    return {
        "provider_name": provider_name,
        "text_char_count": len(full_text),
        "text_block_count": len(layout_blocks),
        "blocks_with_bounding_box_count": len(blocks_with_bbox),
        "blocks_with_confidence_count": len(blocks_with_confidence),
        "layout_available": bool(blocks_with_bbox),
        "provider_metadata_keys": sorted(provider_metadata.keys()),
    }
