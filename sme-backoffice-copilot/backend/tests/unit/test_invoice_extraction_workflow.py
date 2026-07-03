from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.providers import (
    MockLLMProvider,
    ProviderRuntime,
    build_default_provider_routing_config,
)
from app.workflows import (
    ASSEMBLED_INVOICE_DRAFT_KEY,
    CLASSIFICATION_AGENT,
    INVOICE_ASSEMBLY_NODE,
    INVOICE_METADATA_GROUP_KEY,
    INVOICE_TABLE_GROUP_KEY,
    INVOICE_TOTALS_GROUP_KEY,
    METADATA_EXTRACTOR_AGENT,
    OCR_FULL_TEXT_KEY,
    QA_VALIDATION_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    AgentExecutionContext,
    AgentHandoffEnvelope,
    AgentRunStatus,
    ConfidenceLevel,
    HandoffType,
    InvoiceAssemblyNode,
    InvoiceExtractionGroups,
    InvoiceExtractionStatus,
    InvoiceLineItemCandidate,
    InvoiceMetadataGroup,
    InvoiceTableGroup,
    InvoiceTotalsGroup,
    MetadataExtractorAgent,
    QAValidationAgent,
    TableExtractorAgent,
    TotalsExtractorAgent,
    WorkflowStage,
    WorkflowState,
    collect_invoice_groups,
    create_total_amount_correction_signal,
)


def create_state() -> WorkflowState:
    return WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        workflow_run_id=uuid4(),
    )


def create_context(state: WorkflowState) -> AgentExecutionContext:
    return AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
    )


def create_layout_handoff(
    *,
    state: WorkflowState,
    target_agent: str,
    stage: WorkflowStage,
) -> AgentHandoffEnvelope:
    return AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        source_agent="document_layout_analyzer",
        target_agent=target_agent,
        handoff_type=HandoffType.CONTROL,
        stage=stage,
        payload={
            "layout_groups": {
                "metadata_region": None,
                "table_region": None,
                "totals_region": None,
                "source": "placeholder",
            }
        },
        evidence_refs=["page:1"],
        confidence=ConfidenceLevel.UNKNOWN,
    )


def test_invoice_extraction_group_contracts_are_serializable() -> None:
    metadata = InvoiceMetadataGroup(invoice_number="INV-001")
    table = InvoiceTableGroup(
        line_items=[
            InvoiceLineItemCandidate(
                line_number=1,
                description="SaaS subscription",
                line_total="100.00",
            )
        ]
    )
    totals = InvoiceTotalsGroup(
        subtotal_amount="100.00",
        tax_amount="10.00",
        total_amount="110.00",
    )
    groups = InvoiceExtractionGroups(
        metadata=metadata,
        table=table,
        totals=totals,
    )

    assert groups.missing_group_names == []
    payload = groups.model_dump(mode="json")
    assert payload["metadata"]["invoice_number"] == "INV-001"
    assert payload["table"]["line_items"][0]["line_total"] == "100.00"
    assert payload["totals"]["total_amount"] == "110.00"


def test_invoice_group_contracts_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InvoiceMetadataGroup.model_validate(
            {
                "invoice_number": "INV-001",
                "unexpected": "not allowed",
            }
        )


@pytest.mark.asyncio
async def test_metadata_table_and_totals_extractors_route_to_invoice_assembly() -> None:
    state = create_state()
    context = create_context(state)

    metadata_result = await MetadataExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=METADATA_EXTRACTOR_AGENT,
            stage=WorkflowStage.METADATA_EXTRACTION,
        ),
    )
    table_result = await TableExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TABLE_EXTRACTOR_AGENT,
            stage=WorkflowStage.TABLE_EXTRACTION,
        ),
    )
    totals_result = await TotalsExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TOTALS_EXTRACTOR_AGENT,
            stage=WorkflowStage.TOTALS_EXTRACTION,
        ),
    )

    assert metadata_result.status == AgentRunStatus.SUCCEEDED
    assert table_result.status == AgentRunStatus.SUCCEEDED
    assert totals_result.status == AgentRunStatus.SUCCEEDED
    assert INVOICE_METADATA_GROUP_KEY in state.scratchpad
    assert INVOICE_TABLE_GROUP_KEY in state.scratchpad
    assert INVOICE_TOTALS_GROUP_KEY in state.scratchpad
    assert {
        metadata_result.handoffs[0].target_agent,
        table_result.handoffs[0].target_agent,
        totals_result.handoffs[0].target_agent,
    } == {INVOICE_ASSEMBLY_NODE}
    assert all(
        result.handoffs[0].handoff_type == HandoffType.DATA
        for result in [metadata_result, table_result, totals_result]
    )

    groups = collect_invoice_groups(state)
    assert groups.missing_group_names == []


@pytest.mark.asyncio
async def test_invoice_extractors_run_llm_provider_and_validate_contracts() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = (
        "Invoice #INV-MOCK-001\n"
        "Supplier: Mock Supplier Ltd\n"
        "Customer: SME Demo Company\n"
        "Subtotal: 100.00\n"
        "Tax: 10.00\n"
        "Total: 110.00\n"
        "Currency: USD"
    )
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=MockLLMProvider(),
    )

    metadata_result = await MetadataExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=METADATA_EXTRACTOR_AGENT,
            stage=WorkflowStage.METADATA_EXTRACTION,
        ),
    )
    table_result = await TableExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TABLE_EXTRACTOR_AGENT,
            stage=WorkflowStage.TABLE_EXTRACTION,
        ),
    )
    totals_result = await TotalsExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TOTALS_EXTRACTOR_AGENT,
            stage=WorkflowStage.TOTALS_EXTRACTION,
        ),
    )

    assert metadata_result.status == AgentRunStatus.SUCCEEDED
    assert table_result.status == AgentRunStatus.SUCCEEDED
    assert totals_result.status == AgentRunStatus.SUCCEEDED
    assert metadata_result.confidence == ConfidenceLevel.HIGH
    assert table_result.metrics == {"line_item_count": 1}

    groups = collect_invoice_groups(state)

    assert groups.metadata is not None
    assert groups.metadata.extraction_status == InvoiceExtractionStatus.EXTRACTED
    assert groups.metadata.invoice_number == "INV-MOCK-001"
    assert groups.table is not None
    assert groups.table.extraction_status == InvoiceExtractionStatus.EXTRACTED
    assert groups.table.line_items[0].description == "Mock consulting service"
    assert groups.totals is not None
    assert groups.totals.extraction_status == InvoiceExtractionStatus.EXTRACTED
    assert groups.totals.total_amount == "110.00"


@pytest.mark.asyncio
async def test_invoice_assembly_node_combines_groups_and_routes_to_qa() -> None:
    state = create_state()
    context = create_context(state)
    state.scratchpad[INVOICE_METADATA_GROUP_KEY] = InvoiceMetadataGroup(
        invoice_number="INV-001"
    ).model_dump(mode="json")
    state.scratchpad[INVOICE_TABLE_GROUP_KEY] = InvoiceTableGroup().model_dump(
        mode="json"
    )
    state.scratchpad[INVOICE_TOTALS_GROUP_KEY] = InvoiceTotalsGroup().model_dump(
        mode="json"
    )

    result = await InvoiceAssemblyNode().run(state=state, context=context)

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["assembly_status"] == InvoiceExtractionStatus.EXTRACTED.value
    assert result.output["missing_group_names"] == []
    assert ASSEMBLED_INVOICE_DRAFT_KEY in state.scratchpad
    assert result.handoffs[0].source_agent == INVOICE_ASSEMBLY_NODE
    assert result.handoffs[0].target_agent == QA_VALIDATION_AGENT
    assert result.handoffs[0].stage == WorkflowStage.QA_VALIDATION


@pytest.mark.asyncio
async def test_qa_validation_agent_routes_valid_placeholder_to_classification() -> None:
    state = create_state()
    context = create_context(state)
    state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY] = {"schema_version": "test"}

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.SUCCEEDED
    assert result.output["validation_status"] == "passed_placeholder"
    assert result.handoffs[0].source_agent == QA_VALIDATION_AGENT
    assert result.handoffs[0].target_agent == CLASSIFICATION_AGENT
    assert result.handoffs[0].stage == WorkflowStage.CLASSIFICATION


@pytest.mark.asyncio
async def test_qa_validation_agent_routes_targeted_self_correction() -> None:
    state = create_state()
    context = create_context(state)
    signal = create_total_amount_correction_signal(
        expected_value="110.00",
        observed_value="120.00",
        evidence_refs=["page:1:bbox:300,700,520,760"],
    )
    state.qa_error_signals.append(signal)

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.RETRY_REQUESTED
    assert result.output["validation_status"] == "correction_required"
    assert result.qa_error_signals == [signal]
    assert len(result.handoffs) == 1

    correction_handoff = result.handoffs[0]
    assert correction_handoff.source_agent == QA_VALIDATION_AGENT
    assert correction_handoff.target_agent == TOTALS_EXTRACTOR_AGENT
    assert correction_handoff.handoff_type == HandoffType.CORRECTION
    assert correction_handoff.stage == WorkflowStage.TOTALS_EXTRACTION
    assert correction_handoff.qa_error_signal == signal
    assert correction_handoff.payload["field_path"] == "invoice.total_amount"
