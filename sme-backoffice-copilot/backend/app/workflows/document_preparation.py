"""Document preparation agent skeletons for the workflow entry path."""

from __future__ import annotations

from typing import cast

from app.observability.tracing import record_trace_event
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
OCR_LAYOUT_REGIONS_KEY = "ocr_layout_regions"
# Key used to signal that Azure DI prebuilt-invoice already extracted structured
# invoice groups into the scratchpad — extractor agents check this to skip LLM calls.
PREBUILT_INVOICE_EXTRACTION_KEY = "prebuilt_invoice_extraction_source"

DOCUMENT_REGION_NAMES = (
    "header",
    "supplier",
    "bill_to",
    "ship_to",
    "line_item_table",
    "totals",
    "footer",
)


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
            target_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            stage=WorkflowStage.LAYOUT_ANALYSIS,
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
        """Allow local processing, de-identify sensitive data, and route to extraction."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=PRIVACY_POLICY_GATE_AGENT,
        )
        if context_error is not None:
            return context_error

        # Retrieve layout and OCR payload from handoff
        extraction_payload = handoff.payload if handoff is not None else {}

        output: dict[str, object] = {
            "policy_decision": "allow",
            "policy_mode": "placeholder",
            "policy_flags": state.policy_flags,
            **extraction_payload,
        }

        # Route to the three downstream extraction agents
        handoffs = [
            build_control_handoff(
                state=state,
                source_agent=PRIVACY_POLICY_GATE_AGENT,
                target_agent=METADATA_EXTRACTOR_AGENT,
                stage=WorkflowStage.METADATA_EXTRACTION,
                payload=output,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
            build_control_handoff(
                state=state,
                source_agent=PRIVACY_POLICY_GATE_AGENT,
                target_agent=TABLE_EXTRACTOR_AGENT,
                stage=WorkflowStage.TABLE_EXTRACTION,
                payload=output,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
            build_control_handoff(
                state=state,
                source_agent=PRIVACY_POLICY_GATE_AGENT,
                target_agent=TOTALS_EXTRACTOR_AGENT,
                stage=WorkflowStage.TOTALS_EXTRACTION,
                payload=output,
                confidence=ConfidenceLevel.UNKNOWN,
            ),
        ]

        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=handoffs,
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

        layout_regions = ocr_layout_regions_from_state(state)
        layout_groups: dict[str, object] = {
            "regions_ref": OCR_LAYOUT_REGIONS_KEY if layout_regions else None,
            "metadata_region": layout_regions.get("header"),
            "supplier_region": layout_regions.get("supplier"),
            "bill_to_region": layout_regions.get("bill_to"),
            "ship_to_region": layout_regions.get("ship_to"),
            "table_region": layout_regions.get("line_item_table"),
            "totals_region": layout_regions.get("totals"),
            "footer_region": layout_regions.get("footer"),
            "source": "ocr_provider" if provider_output is not None else "placeholder",
        }
        output: dict[str, object] = {
            "layout_detected": bool(layout_regions),
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
            "ocr_layout_blocks_ref": OCR_LAYOUT_BLOCKS_KEY
            if provider_output is not None
            else None,
            "ocr_layout_regions_ref": OCR_LAYOUT_REGIONS_KEY
            if layout_regions
            else None,
        }
        next_handoff = build_control_handoff(
            state=state,
            source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            target_agent=PRIVACY_POLICY_GATE_AGENT,
            stage=WorkflowStage.PRIVACY_POLICY_GATE,
            payload=extraction_payload,
            confidence=ConfidenceLevel.UNKNOWN,
        )
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[next_handoff],
            confidence=(
                ConfidenceLevel.MEDIUM
                if provider_output is not None
                else ConfidenceLevel.UNKNOWN
            ),
            metrics={
                "layout_group_count": 3,
                "layout_region_count": len(layout_regions),
            },
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
        record_trace_event(
            context.trace_provider,
            "ocr.call.failed",
            {
                "agent_name": DOCUMENT_LAYOUT_ANALYZER_AGENT,
                "error_code": "ERR_OCR_INPUT_MISSING",
                "provider_name": getattr(context.ocr_provider, "name", None),
            },
            correlation_id=context.correlation_id,
        )
        return AgentRunResult(
            status=AgentRunStatus.FAILED,
            confidence=ConfidenceLevel.HIGH,
            error_code="ERR_OCR_INPUT_MISSING",
            error_message="Document layout analysis requires an original artifact.",
        )

    try:
        record_trace_event(
            context.trace_provider,
            "ocr.call.started",
            {
                "agent_name": DOCUMENT_LAYOUT_ANALYZER_AGENT,
                "provider_name": getattr(context.ocr_provider, "name", None),
                "task_type": ProviderTaskType.DOCUMENT_OCR.value,
                "media_type": getattr(input_data, "media_type", None),
                "has_local_path": getattr(input_data, "local_path", None)
                is not None,
                "workflow_run_id": str(context.workflow_run_id)
                if context.workflow_run_id is not None
                else None,
            },
            correlation_id=context.correlation_id,
        )
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
        record_trace_event(
            context.trace_provider,
            "ocr.call.failed",
            {
                "agent_name": DOCUMENT_LAYOUT_ANALYZER_AGENT,
                "provider_name": getattr(context.ocr_provider, "name", None),
                "task_type": ProviderTaskType.DOCUMENT_OCR.value,
                "error_code": "ERR_OCR_PROVIDER_FAILED",
                "error_type": type(exc).__name__,
            },
            correlation_id=context.correlation_id,
        )
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
    layout_regions = build_ocr_layout_regions(layout_blocks)
    layout_diagnostics = build_ocr_layout_diagnostics(
        provider_name=invocation.result.provider_name,
        full_text=invocation.result.full_text,
        layout_blocks=layout_blocks,
        layout_regions=layout_regions,
        provider_metadata=invocation.result.metadata,
    )
    state.scratchpad[OCR_RESULT_KEY] = ocr_result_payload
    state.scratchpad[OCR_FULL_TEXT_KEY] = invocation.result.full_text
    state.scratchpad[OCR_LAYOUT_BLOCKS_KEY] = layout_blocks
    state.scratchpad[OCR_LAYOUT_REGIONS_KEY] = layout_regions
    state.scratchpad[OCR_LAYOUT_DIAGNOSTICS_KEY] = layout_diagnostics
    # Pre-populate invoice extraction groups when the provider already extracted
    # structured fields (i.e. Azure DI prebuilt-invoice model was used).
    populate_scratchpad_from_prebuilt_extraction(
        state=state,
        ocr_result_metadata=invocation.result.metadata,
    )
    record_trace_event(
        context.trace_provider,
        "ocr.call.finished",
        {
            "agent_name": DOCUMENT_LAYOUT_ANALYZER_AGENT,
            "provider_name": invocation.result.provider_name,
            "task_type": invocation.route.task_type.value,
            "deployment_mode": invocation.route.deployment_mode.value,
            "attempts": invocation.attempts,
            "full_text_length": len(invocation.result.full_text),
            "text_block_count": len(invocation.result.text_blocks),
            "layout_block_count": len(layout_blocks),
            "layout_region_count": len(layout_regions),
            "privacy_action": invocation.privacy_decision.action.value
            if invocation.privacy_decision is not None
            else None,
        },
        correlation_id=context.correlation_id,
    )
    return {
        "provider_name": invocation.result.provider_name,
        "full_text_length": len(invocation.result.full_text),
        "text_block_count": len(invocation.result.text_blocks),
        OCR_LAYOUT_DIAGNOSTICS_KEY: layout_diagnostics,
    }


def populate_scratchpad_from_prebuilt_extraction(
    *,
    state: WorkflowState,
    ocr_result_metadata: dict[str, object],
) -> None:
    """Write Azure DI prebuilt-invoice extraction groups into the workflow scratchpad.

    When the OCR provider used the ``prebuilt-invoice`` model, the resulting
    ``OCRResult.metadata`` will contain a ``"prebuilt_invoice_extraction"`` key
    whose value is a dict with ``metadata_group``, ``table_group``, and
    ``totals_group`` sub-dicts that already conform to the internal invoice
    extraction contracts.

    This function reads those groups and writes them directly into the
    workflow scratchpad under the canonical keys used by the three extractor
    agents (``INVOICE_METADATA_GROUP_KEY``, ``INVOICE_TABLE_GROUP_KEY``,
    ``INVOICE_TOTALS_GROUP_KEY``).  It also records a provenance sentinel under
    ``PREBUILT_INVOICE_EXTRACTION_KEY`` so that each extractor agent can detect
    the fast-path and skip its LLM call.

    If no prebuilt extraction is present in the OCR metadata, this function is a
    no-op — preserving full backward compatibility with ``prebuilt-layout``.
    """
    from app.workflows.invoice_extraction import (
        INVOICE_METADATA_GROUP_KEY,
        INVOICE_TABLE_GROUP_KEY,
        INVOICE_TOTALS_GROUP_KEY,
    )

    prebuilt = ocr_result_metadata.get("prebuilt_invoice_extraction")
    if not isinstance(prebuilt, dict) or not prebuilt:
        return

    key_map = {
        "metadata_group": INVOICE_METADATA_GROUP_KEY,
        "table_group": INVOICE_TABLE_GROUP_KEY,
        "totals_group": INVOICE_TOTALS_GROUP_KEY,
    }
    populated: list[str] = []
    for source_key, scratchpad_key in key_map.items():
        group = prebuilt.get(source_key)
        if isinstance(group, dict):
            state.scratchpad[scratchpad_key] = group
            populated.append(scratchpad_key)

    if populated:
        # Record provenance: which groups were pre-populated and by which model
        state.scratchpad[PREBUILT_INVOICE_EXTRACTION_KEY] = {
            "source": "azure_di:prebuilt-invoice",
            "populated_groups": populated,
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


def build_ocr_layout_regions(
    layout_blocks: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Group OCR blocks into coarse invoice regions for downstream agents."""

    regions = build_document_region_contracts()
    if not layout_blocks:
        return regions

    table_start = first_block_index_matching(
        layout_blocks,
        ("description", "particulars", "qty", "quantity"),
    )
    totals_start = first_block_index_matching(
        layout_blocks,
        ("subtotal", "sub total", "tax", "vat", "balance due"),
        start_at=table_start + 1 if table_start is not None else 0,
    )
    bill_to_start = first_block_index_matching(
        layout_blocks,
        ("bill to", "bill to:", "customer", "client"),
    )
    ship_to_start = first_block_index_matching(layout_blocks, ("ship to", "ship to:"))

    for index, block in enumerate(layout_blocks):
        region_name = infer_region_name(
            index=index,
            table_start=table_start,
            totals_start=totals_start,
            bill_to_start=bill_to_start,
            ship_to_start=ship_to_start,
            block_count=len(layout_blocks),
        )
        add_block_to_region(regions[region_name], block)

    return {name: region for name, region in regions.items() if region["block_ids"]}


def build_document_region_contracts() -> dict[str, dict[str, object]]:
    """Return empty provider-neutral document region contracts."""

    return {
        name: {
            "region_type": name,
            "block_ids": [],
            "text": "",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        }
        for name in DOCUMENT_REGION_NAMES
    }


def first_block_index_matching(
    layout_blocks: list[dict[str, object]],
    needles: tuple[str, ...],
    *,
    start_at: int = 0,
) -> int | None:
    """Return first block index containing any marker text."""

    for index, block in enumerate(layout_blocks[start_at:], start=start_at):
        text = block.get("text")
        if not isinstance(text, str):
            continue
        normalized = text.casefold()
        if any(needle in normalized for needle in needles):
            return index
    return None


def infer_region_name(
    *,
    index: int,
    table_start: int | None,
    totals_start: int | None,
    bill_to_start: int | None,
    ship_to_start: int | None,
    block_count: int,
) -> str:
    """Infer the coarse document region for an OCR block index."""

    if totals_start is not None and index >= totals_start:
        return "totals" if index < block_count - 3 else "footer"
    if table_start is not None and index >= table_start:
        return "line_item_table"
    if ship_to_start is not None and index >= ship_to_start:
        return "ship_to"
    if bill_to_start is not None and index >= bill_to_start:
        return "bill_to"
    return "supplier" if index > 0 else "header"


def add_block_to_region(
    region: dict[str, object],
    block: dict[str, object],
) -> None:
    """Append one OCR block to a normalized region contract."""

    block_id = block.get("id")
    block_ids = region["block_ids"]
    if isinstance(block_id, str) and isinstance(block_ids, list):
        block_ids.append(block_id)

    text = block.get("text")
    if isinstance(text, str):
        existing_text = region["text"]
        region["text"] = (
            f"{existing_text}\n{text}".strip()
            if isinstance(existing_text, str)
            else text
        )

    region["bounding_box"] = merge_region_bounding_box(
        region.get("bounding_box"),
        block.get("bounding_box"),
    )

    confidence = block.get("confidence")
    if isinstance(confidence, int | float):
        current = region.get("confidence")
        region["confidence"] = (
            confidence
            if not isinstance(current, int | float)
            else min(float(current), float(confidence))
        )


def merge_region_bounding_box(
    existing: object,
    incoming: object,
) -> list[float] | None:
    """Merge axis-aligned boxes represented as [x1, y1, x2, y2]."""

    if not is_axis_aligned_bbox(incoming):
        return cast(list[float], existing) if is_axis_aligned_bbox(existing) else None
    incoming_box = cast(list[float], incoming)
    if not is_axis_aligned_bbox(existing):
        return incoming_box
    existing_box = cast(list[float], existing)
    return [
        min(existing_box[0], incoming_box[0]),
        min(existing_box[1], incoming_box[1]),
        max(existing_box[2], incoming_box[2]),
        max(existing_box[3], incoming_box[3]),
    ]


def is_axis_aligned_bbox(value: object) -> bool:
    """Return whether value is a simple [x1, y1, x2, y2] box."""

    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, int | float) for item in value)
    )


def ocr_layout_regions_from_state(
    state: WorkflowState,
) -> dict[str, dict[str, object]]:
    """Return normalized OCR layout regions stored by layout analysis."""

    regions = state.scratchpad.get(OCR_LAYOUT_REGIONS_KEY)
    if not isinstance(regions, dict):
        return {}
    return {
        str(name): region
        for name, region in regions.items()
        if isinstance(region, dict)
    }


def build_ocr_layout_diagnostics(
    *,
    provider_name: str,
    full_text: str,
    layout_blocks: list[dict[str, object]],
    layout_regions: dict[str, dict[str, object]],
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
        "region_count": len(layout_regions),
        "region_names": sorted(layout_regions.keys()),
        "provider_metadata_keys": sorted(provider_metadata.keys()),
    }
