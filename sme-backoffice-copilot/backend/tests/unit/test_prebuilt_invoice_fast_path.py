"""Unit tests for the prebuilt-invoice fast-path skip and fallback logic in the workflows.

Covers:
- Fast-path skip: if a group is already in scratchpad, Metadata/Table/Totals
  ExtractorAgent skips calling the LLM and succeeds instantly.
- Selective fallback: if only one group is missing from scratchpad, only that agent
  calls the LLM. The others skip.
- QA correction bypass: if a QA correction signal is received in the handoff,
  the fast-path is bypassed for that agent so the LLM can run and fix the fields.
"""

from __future__ import annotations

from uuid import uuid4
import pytest
from pydantic import ValidationError

from app.workflows import (
    INVOICE_METADATA_GROUP_KEY,
    INVOICE_TABLE_GROUP_KEY,
    INVOICE_TOTALS_GROUP_KEY,
    AgentExecutionContext,
    AgentHandoffEnvelope,
    AgentRunStatus,
    ConfidenceLevel,
    HandoffType,
    MetadataExtractorAgent,
    TableExtractorAgent,
    TotalsExtractorAgent,
    WorkflowStage,
    WorkflowState,
    create_total_amount_correction_signal,
)
from app.workflows.invoice_extraction import is_scratchpad_group_populated
from app.providers import MockLLMProvider, ProviderRuntime, build_default_provider_routing_config


# ─── Mock LLM Provider that tracks invocations ────────────────────────────────


class InvocationsTrackingLLMProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        # Must match the expected provider name from the default routing configuration
        return "mock_llm"

    async def generate(self, *, request, context):  # type: ignore[no-untyped-def]
        self.calls.append(request.response_schema_name)
        # Return standard mock responses to avoid validation errors
        if request.response_schema_name == "invoice-metadata-group.v1":
            structured_output = {
                "schema_version": "invoice-metadata-group.v1",
                "extraction_status": "extracted",
                "invoice_number": "INV-123",
                "supplier_name": "Supplier Co",
                "customer_name": "Customer Inc",
                "evidence_refs": [],
                "confidence": "high",
            }
        elif request.response_schema_name == "invoice-table-group.v1":
            structured_output = {
                "schema_version": "invoice-table-group.v1",
                "extraction_status": "extracted",
                "line_items": [
                    {
                        "line_number": 1,
                        "description": "Item 1",
                        "quantity": "1.0",
                        "unit_price": "100.00",
                        "line_total": "100.00",
                        "evidence_refs": [],
                        "confidence": "high",
                    }
                ],
                "evidence_refs": [],
                "confidence": "high",
            }
        else:
            structured_output = {
                "schema_version": "invoice-totals-group.v1",
                "extraction_status": "extracted",
                "subtotal_amount": "100.00",
                "tax_amount": "0.00",
                "total_amount": "100.00",
                "currency": "USD",
                "evidence_refs": [],
                "confidence": "high",
            }
        from app.providers.llm import LLMGenerationResult
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="mock-model",
            output_text="{}",
            structured_output=structured_output,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_context(state: WorkflowState, llm_provider) -> AgentExecutionContext:  # type: ignore[no-untyped-def]
    return AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=uuid4(),
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=llm_provider,
        ocr_provider=None,
    )


def _make_state() -> WorkflowState:
    state = WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
    )
    # Ensure some fallback OCR text is present to prevent layout analytical fallbacks from crashing
    state.scratchpad["ocr_full_text"] = "Invoice # INV-123\nTotal $100.00"
    return state


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_is_scratchpad_group_populated_conditions() -> None:
    state = _make_state()
    assert not is_scratchpad_group_populated(
        state=state,
        scratchpad_key=INVOICE_METADATA_GROUP_KEY,
        handoff=None,
    )

    state.scratchpad[INVOICE_METADATA_GROUP_KEY] = {"invoice_number": "INV-123"}
    assert is_scratchpad_group_populated(
        state=state,
        scratchpad_key=INVOICE_METADATA_GROUP_KEY,
        handoff=None,
    )

    # QA Correction Signal received in handoff should bypass fast-path
    correction_signal = create_total_amount_correction_signal(
        expected_value="100.00", observed_value="120.00", evidence_refs=[]
    )
    handoff_envelope = AgentHandoffEnvelope(
        handoff_id=uuid4(),
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=uuid4(),
        source_agent="qa_validator",
        target_agent="metadata_extractor",
        handoff_type=HandoffType.CORRECTION,
        stage=WorkflowStage.METADATA_EXTRACTION,
        payload={},
        qa_error_signal=correction_signal,
    )
    assert not is_scratchpad_group_populated(
        state=state,
        scratchpad_key=INVOICE_METADATA_GROUP_KEY,
        handoff=handoff_envelope,
    )


@pytest.mark.asyncio
async def test_fast_path_skip_all_agents() -> None:
    """If all three groups are already populated in scratchpad, no LLM calls are made."""
    state = _make_state()
    # Pre-populate scratchpad
    state.scratchpad[INVOICE_METADATA_GROUP_KEY] = {
        "schema_version": "invoice-metadata-group.v1",
        "extraction_status": "extracted",
        "invoice_number": "INV-123",
        "confidence": "high",
        "evidence_refs": [],
    }
    state.scratchpad[INVOICE_TABLE_GROUP_KEY] = {
        "schema_version": "invoice-table-group.v1",
        "extraction_status": "extracted",
        "line_items": [],
        "confidence": "high",
        "evidence_refs": [],
    }
    state.scratchpad[INVOICE_TOTALS_GROUP_KEY] = {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "extracted",
        "total_amount": "100.00",
        "confidence": "high",
        "evidence_refs": [],
    }

    tracking_provider = InvocationsTrackingLLMProvider()
    context = _make_context(state, tracking_provider)

    # Run agents
    res_m = await MetadataExtractorAgent().run(state=state, context=context)
    res_t = await TableExtractorAgent().run(state=state, context=context)
    res_tot = await TotalsExtractorAgent().run(state=state, context=context)

    # Verify they all succeeded
    assert res_m.status == AgentRunStatus.SUCCEEDED
    assert res_t.status == AgentRunStatus.SUCCEEDED
    assert res_tot.status == AgentRunStatus.SUCCEEDED

    # Verify no LLM calls were made
    assert tracking_provider.calls == []
    # Verify outputs include fast_path flag
    assert res_m.output.get("fast_path") is True
    assert res_t.output.get("fast_path") is True
    assert res_tot.output.get("fast_path") is True


@pytest.mark.asyncio
async def test_adaptive_fallback_single_agent_executes() -> None:
    """If metadata is missing but table and totals are present, only MetadataExtractorAgent runs LLM."""
    state = _make_state()
    # Pre-populate table and totals, leave metadata empty
    state.scratchpad[INVOICE_TABLE_GROUP_KEY] = {
        "schema_version": "invoice-table-group.v1",
        "extraction_status": "extracted",
        "line_items": [],
        "confidence": "high",
        "evidence_refs": [],
    }
    state.scratchpad[INVOICE_TOTALS_GROUP_KEY] = {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "extracted",
        "total_amount": "100.00",
        "confidence": "high",
        "evidence_refs": [],
    }

    tracking_provider = InvocationsTrackingLLMProvider()
    context = _make_context(state, tracking_provider)

    # Run agents
    res_m = await MetadataExtractorAgent().run(state=state, context=context)
    res_t = await TableExtractorAgent().run(state=state, context=context)
    res_tot = await TotalsExtractorAgent().run(state=state, context=context)

    assert res_m.status == AgentRunStatus.SUCCEEDED
    assert res_t.status == AgentRunStatus.SUCCEEDED
    assert res_tot.status == AgentRunStatus.SUCCEEDED

    # Only metadata LLM schema should have been called
    assert tracking_provider.calls == ["invoice-metadata-group.v1"]
    assert res_m.output.get("fast_path") is not True
    assert res_t.output.get("fast_path") is True
    assert res_tot.output.get("fast_path") is True


@pytest.mark.asyncio
async def test_qa_correction_bypasses_fast_path() -> None:
    """If a QA correction signal is received, the agent executes LLM despite scratchpad data."""
    state = _make_state()
    state.scratchpad[INVOICE_TOTALS_GROUP_KEY] = {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "extracted",
        "total_amount": "120.00",
        "confidence": "high",
        "evidence_refs": [],
    }

    tracking_provider = InvocationsTrackingLLMProvider()
    context = _make_context(state, tracking_provider)

    correction_signal = create_total_amount_correction_signal(
        expected_value="100.00", observed_value="120.00", evidence_refs=[]
    )
    handoff_envelope = AgentHandoffEnvelope(
        handoff_id=uuid4(),
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=uuid4(),
        source_agent="qa_validator",
        target_agent="totals_extractor",
        handoff_type=HandoffType.CORRECTION,
        stage=WorkflowStage.TOTALS_EXTRACTION,
        payload={},
        qa_error_signal=correction_signal,
    )

    res_tot = await TotalsExtractorAgent().run(state=state, context=context, handoff=handoff_envelope)

    # Totals agent must invoke LLM because of the correction signal
    assert tracking_provider.calls == ["invoice-totals-group.v1"]
    assert res_tot.status == AgentRunStatus.SUCCEEDED
    assert res_tot.output.get("fast_path") is not True
