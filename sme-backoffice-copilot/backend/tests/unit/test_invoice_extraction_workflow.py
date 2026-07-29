from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.providers import (
    MockLLMProvider,
    ProviderRuntime,
    build_default_provider_routing_config,
)
from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderRunContext,
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
    OCR_LAYOUT_REGIONS_KEY,
    QA_VALIDATION_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    AgentExecutionContext,
    AgentHandoffEnvelope,
    AgentRunStatus,
    AssembledInvoiceDraft,
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
from app.workflows.invoice_extraction import (
    PROVIDER_EXTRACTION_ERRORS_KEY,
    build_extraction_routing_decision,
    merge_provider_payload_with_ocr_fallback,
    normalize_provider_invoice_group_payload,
    ocr_context_for_schema,
)

COMMON_INVOICE_OCR_TEXT = """Your Company Inc.
1234 Company St,
Company Town, ST 12345

INVOICE

Bill To
Customer Name
1234 Customer St,
Customer Town, ST 12345

Invoice # 0000007
Invoice date 10-02-2023
Due date 10-16-2023

QTY Description Unit Price Amount
1.00 Replacement of spark plugs 40.00 $40.00
2.00 Brake pad replacement ( front ) 40.00 $80.00
4.00 Wheel alignment 17.50 $70.00
2.00 Mechanic's rate per hour 30.00 $60.00

Subtotal $250.00
Sales Tax (5%) $12.50
Total (USD) $262.50
"""


class InvalidStructuredOutputLLMProvider:
    @property
    def name(self) -> str:
        return "mock_llm"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        del request, context
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="invalid-structured-output",
            output_text='{"unexpected":"shape"}',
            structured_output={"unexpected": "shape"},
        )


class OllamaStyleStructuredOutputLLMProvider:
    @property
    def name(self) -> str:
        return "mock_llm"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        del context
        if request.response_schema_name == "invoice-metadata-group.v1":
            structured_output: dict[str, object] = {
                "invoiceMetadata": {
                    "invoiceNumber": "0000007",
                    "invoiceDate": "2023-10-02",
                    "dueDate": "2023-10-16",
                    "currency": "USD",
                },
                "party": {
                    "issuer": {"name": "Your Company Inc."},
                    "billTo": {"name": "Customer Name"},
                },
            }
        elif request.response_schema_name == "invoice-table-group.v1":
            structured_output = {
                "items": [
                    {
                        "description": "Replacement of spark plugs",
                        "quantity": 1,
                        "unitPrice": "40.00",
                        "amount": "$40.00",
                    },
                    {
                        "description": "Brake pad replacement (front)",
                        "qty": "2.00",
                        "price": 40.0,
                        "total": "$80.00",
                    },
                ]
            }
        else:
            structured_output = {
                "invoice_subtotal": 250.0,
                "tax": 12.5,
                "total": 262.5,
                "currency": "USD",
            }
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="llama3.1:8b",
            output_text="{}",
            structured_output=structured_output,
        )


class CapturingLLMProvider:
    def __init__(self) -> None:
        self.requests: list[LLMGenerationRequest] = []

    @property
    def name(self) -> str:
        return "mock_llm"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        del context
        self.requests.append(request)
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="capture",
            output_text="{}",
            structured_output={
                "schema_version": "invoice-table-group.v1",
                "extraction_status": "extracted",
                "line_items": [
                    {
                        "line_number": 1,
                        "description": "Region item",
                        "quantity": "1.00",
                        "unit_price": "10.00",
                        "tax_amount": None,
                        "line_total": "10.00",
                        "evidence_refs": [],
                        "confidence": "medium",
                    }
                ],
                "table_region_ref": "ocr:region:line_item_table",
                "evidence_refs": [],
                "confidence": "medium",
            },
        )


class CountingOllamaProvider:
    def __init__(self) -> None:
        self.requests: list[LLMGenerationRequest] = []

    @property
    def name(self) -> str:
        return "ollama"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        del context
        self.requests.append(request)
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="qwen2.5:7b",
            output_text="{}",
            structured_output={
                "schema_version": "invoice-metadata-group.v1",
                "extraction_status": "extracted",
                "invoice_number": "LLM-001",
                "supplier_name": "LLM Supplier",
                "supplier_tax_id": None,
                "customer_name": None,
                "customer_tax_id": None,
                "issue_date": "2026-07-28",
                "due_date": None,
                "currency": "EUR",
                "evidence_refs": [],
                "confidence": "medium",
            },
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


def test_totals_normalizer_converts_schema_shaped_numeric_amounts() -> None:
    payload = normalize_provider_invoice_group_payload(
        schema_name="invoice-totals-group.v1",
        payload={
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": "extracted",
            "subtotal_amount": 250,
            "tax_amount": 12.5,
            "total_amount": 262.5,
            "currency": "USD",
            "evidence_refs": [],
            "confidence": "medium",
        },
    )

    totals = InvoiceTotalsGroup.model_validate(payload)

    assert totals.subtotal_amount == "250.00"
    assert totals.tax_amount == "12.50"
    assert totals.total_amount == "262.50"


def test_table_normalizer_sanitizes_duplicate_hallucinated_totals() -> None:
    payload = normalize_provider_invoice_group_payload(
        schema_name="invoice-table-group.v1",
        payload={
            "schema_version": "invoice-table-group.v1",
            "extraction_status": "extracted",
            "line_items": [
                {
                    "line_number": 1,
                    "description": "SERVICE RSLL AUTOCARSS",
                    "quantity": "1.00",
                    "unit_price": "1300.00",
                    "line_total": "1300.00",
                },
                {
                    "line_number": 2,
                    "description": "CONITECH TIMING CHAIN KIT+WHATER PUMP",
                    "quantity": None,
                    "unit_price": None,
                    "line_total": "1300.00",
                },
                {
                    "line_number": 3,
                    "description": "CASTROL OIL 5L 5W30",
                    "quantity": "—",
                    "unit_price": None,
                    "line_total": "1300.00",
                },
                {
                    "line_number": 4,
                    "description": "ANTIFREEZER COOLANT",
                    "quantity": None,
                    "unit_price": None,
                    "line_total": "1300.00",
                },
            ],
            "evidence_refs": [],
            "confidence": "medium",
        },
    )

    table = InvoiceTableGroup.model_validate(payload)

    # Item 1 should preserve its total
    assert table.line_items[0].line_total == "1300.00"
    # Items 2, 3, 4 should have their line_total cleared to None
    assert table.line_items[1].line_total is None
    assert table.line_items[2].line_total is None
    assert table.line_items[3].line_total is None


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
async def test_local_complete_metadata_and_explicit_total_skip_ollama() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = COMMON_INVOICE_OCR_TEXT
    llm_provider = CountingOllamaProvider()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(
            build_default_provider_routing_config(llm_provider_name="ollama")
        ),
        llm_provider=llm_provider,
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
    totals_result = await TotalsExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TOTALS_EXTRACTOR_AGENT,
            stage=WorkflowStage.TOTALS_EXTRACTION,
        ),
    )

    assert llm_provider.requests == []
    assert metadata_result.metrics["llm_invoked"] is False
    assert metadata_result.output["routing"]["strategy"] == "deterministic_fast_path"
    assert totals_result.metrics["llm_invoked"] is False
    assert totals_result.output["routing"]["strategy"] == "deterministic_fast_path"


@pytest.mark.asyncio
async def test_local_incomplete_metadata_invokes_ollama_for_weak_fields() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = "Invoice # LOCAL-001"
    llm_provider = CountingOllamaProvider()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(
            build_default_provider_routing_config(llm_provider_name="ollama")
        ),
        llm_provider=llm_provider,
    )

    result = await MetadataExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=METADATA_EXTRACTOR_AGENT,
            stage=WorkflowStage.METADATA_EXTRACTION,
        ),
    )

    assert len(llm_provider.requests) == 1
    assert result.metrics["llm_invoked"] is True
    assert result.output["routing"]["strategy"] == "llm_fallback"
    assert set(result.output["routing"]["missing_required_fields"]) == {
        "supplier_name",
        "issue_date",
    }
    prompt = "\n".join(message.content for message in llm_provider.requests[0].messages)
    assert "unresolved or weak fields" in prompt


def test_supplier_quality_gate_routes_truncated_name_to_llm() -> None:
    decision = build_extraction_routing_decision(
        schema_name="invoice-metadata-group.v1",
        deterministic_payload={
            "invoice_number": "A/123",
            "supplier_name": "Esil. rarques de",
            "issue_date": "2019-01-17",
            "confidence": "medium",
        },
        llm_provider_name="ollama",
        handoff=None,
    )

    assert decision["llm_invoked"] is True
    assert decision["missing_required_fields"] == ["supplier_name"]
    assert decision["low_quality_fields"] == ["supplier_name"]


def test_supplier_quality_gate_keeps_complete_company_name_on_fast_path() -> None:
    decision = build_extraction_routing_decision(
        schema_name="invoice-metadata-group.v1",
        deterministic_payload={
            "invoice_number": "19FT 002/46",
            "supplier_name": "FERRAGENS IDEAL DA BOAVISA A",
            "issue_date": "2019-01-11",
            "confidence": "medium",
        },
        llm_provider_name="ollama",
        handoff=None,
    )

    assert decision["llm_invoked"] is False
    assert decision["low_quality_fields"] == []


@pytest.mark.parametrize("supplier_name", ["ARROTOS", "PORTUGAL", "SULAMAN"])
def test_supplier_quality_gate_keeps_single_token_names_on_fast_path(
    supplier_name: str,
) -> None:
    decision = build_extraction_routing_decision(
        schema_name="invoice-metadata-group.v1",
        deterministic_payload={
            "invoice_number": "A/26752",
            "supplier_name": supplier_name,
            "issue_date": "2019-02-04",
            "confidence": "medium",
        },
        llm_provider_name="ollama",
        handoff=None,
    )

    assert decision["llm_invoked"] is False
    assert decision["low_quality_fields"] == []


@pytest.mark.asyncio
async def test_invoice_extractors_fallback_to_ocr_text_when_llm_schema_fails() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = COMMON_INVOICE_OCR_TEXT
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=InvalidStructuredOutputLLMProvider(),
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

    groups = collect_invoice_groups(state)

    assert groups.metadata is not None
    assert groups.metadata.invoice_number == "0000007"
    assert groups.metadata.supplier_name == "Your Company Inc."
    assert groups.metadata.customer_name == "Customer Name"
    assert groups.metadata.issue_date == "2023-10-02"
    assert groups.table is not None
    assert len(groups.table.line_items) == 4
    assert groups.table.line_items[0].description == "Replacement of spark plugs"
    assert groups.totals is not None
    assert groups.totals.subtotal_amount == "250.00"
    assert groups.totals.tax_amount == "12.50"
    assert groups.totals.total_amount == "262.50"
    assert PROVIDER_EXTRACTION_ERRORS_KEY in state.scratchpad


@pytest.mark.asyncio
async def test_invoice_extractors_normalize_ollama_style_json_shapes() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = COMMON_INVOICE_OCR_TEXT
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=OllamaStyleStructuredOutputLLMProvider(),
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

    groups = collect_invoice_groups(state)

    assert groups.metadata is not None
    assert groups.metadata.invoice_number == "0000007"
    assert groups.metadata.supplier_name == "Your Company Inc."
    assert groups.metadata.customer_name == "Customer Name"
    assert groups.metadata.issue_date == "2023-10-02"
    assert groups.table is not None
    assert len(groups.table.line_items) == 2
    assert groups.table.line_items[0].line_total == "40.00"
    assert groups.table.line_items[1].unit_price == "40.00"
    assert groups.totals is not None
    assert groups.totals.subtotal_amount == "250.00"
    assert groups.totals.tax_amount == "12.50"
    assert groups.totals.total_amount == "262.50"
    assert PROVIDER_EXTRACTION_ERRORS_KEY not in state.scratchpad


@pytest.mark.asyncio
async def test_table_extractor_prefers_layout_region_over_full_ocr_text() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = (
        "Supplier: Header Supplier\n"
        "Description Qty Unit Total\n"
        "Region item 1.00 10.00 10.00\n"
        "Footer terms should stay outside table prompt"
    )
    state.scratchpad[OCR_LAYOUT_REGIONS_KEY] = {
        "line_item_table": {
            "region_type": "line_item_table",
            "block_ids": ["ocr:block:2"],
            "text": "Description Qty Unit Total\nRegion item 1.00 10.00 10.00",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        }
    }
    llm_provider = CapturingLLMProvider()
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=llm_provider,
    )

    result = await TableExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=TABLE_EXTRACTOR_AGENT,
            stage=WorkflowStage.TABLE_EXTRACTION,
        ),
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    assert len(llm_provider.requests) == 1
    prompt_text = "\n".join(
        message.content for message in llm_provider.requests[0].messages
    )
    assert "Region item 1.00 10.00 10.00" in prompt_text
    assert "Header Supplier" not in prompt_text
    assert "Footer terms" not in prompt_text


def test_metadata_extractor_uses_full_ocr_text_instead_of_layout_subset() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = (
        "Supplier SA\nNIF: 502689390\nCliente: Buyer LDA\nContribuinte: 510776914"
    )
    state.scratchpad[OCR_LAYOUT_REGIONS_KEY] = {
        "header": {
            "region_type": "header",
            "block_ids": ["ocr:block:1"],
            "text": "Supplier SA",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        }
    }

    context_text = ocr_context_for_schema(
        state=state,
        schema_name="invoice-metadata-group.v1",
    )

    assert "NIF: 502689390" in context_text
    assert "Contribuinte: 510776914" in context_text


def test_totals_extractor_uses_full_ocr_text_instead_of_layout_subset() -> None:
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = "Items\nTotal a Pagar:\n19,98 €"
    state.scratchpad[OCR_LAYOUT_REGIONS_KEY] = {
        "totals": {
            "region_type": "totals",
            "block_ids": ["ocr:block:9"],
            "text": "Total\n1998",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        }
    }

    context_text = ocr_context_for_schema(
        state=state,
        schema_name="invoice-totals-group.v1",
    )

    assert context_text == "Items\nTotal a Pagar:\n19,98 €"


def test_explicit_deterministic_total_overrides_llm_amount() -> None:
    merged = merge_provider_payload_with_ocr_fallback(
        schema_name="invoice-totals-group.v1",
        provider_payload={
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": "extracted",
            "subtotal_amount": None,
            "tax_amount": "374.00",
            "total_amount": "1998.00",
            "currency": "EUR",
            "evidence_refs": [],
            "confidence": "medium",
        },
        fallback_payload={
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": "partial",
            "subtotal_amount": None,
            "tax_amount": None,
            "total_amount": "19.98",
            "currency": "EUR",
            "evidence_refs": ["ocr:text:fallback:totals"],
            "confidence": "high",
        },
    )

    assert merged["total_amount"] == "19.98"
    assert merged["tax_amount"] == "374.00"


def test_unlabelled_deterministic_total_does_not_override_llm_amount() -> None:
    merged = merge_provider_payload_with_ocr_fallback(
        schema_name="invoice-totals-group.v1",
        provider_payload={
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": "extracted",
            "total_amount": "49.99",
            "evidence_refs": [],
            "confidence": "medium",
        },
        fallback_payload={
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": "partial",
            "total_amount": "9.99",
            "evidence_refs": ["ocr:text:fallback:totals"],
            "confidence": "medium",
        },
    )

    assert merged["total_amount"] == "49.99"


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
async def test_qa_validation_agent_flags_financially_incomplete_draft() -> None:
    state = create_state()
    context = create_context(state)
    draft = AssembledInvoiceDraft(
        document_id=state.document_id,
        groups=InvoiceExtractionGroups(
            metadata=InvoiceMetadataGroup(invoice_number="INV-001"),
            table=InvoiceTableGroup(
                extraction_status=InvoiceExtractionStatus.EXTRACTED,
                line_items=[
                    InvoiceLineItemCandidate(
                        line_number=1,
                        description="Service",
                        quantity="1.00",
                        unit_price="100.00",
                        line_total="100.00",
                    )
                ],
            ),
            totals=InvoiceTotalsGroup(
                extraction_status=InvoiceExtractionStatus.EXTRACTED,
                subtotal_amount="100.00",
                tax_amount=None,
                total_amount=None,
            ),
        ),
        assembly_status=InvoiceExtractionStatus.EXTRACTED,
    )
    state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY] = draft.model_dump(mode="json")

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.REVIEW_REQUIRED
    assert result.output["validation_status"] == "review_required"
    assert any(
        signal.code == "ERR_AMOUNT_INVALID" for signal in result.qa_error_signals
    )
    assert result.handoffs == []


@pytest.mark.asyncio
async def test_qa_validation_agent_flags_subtotal_line_item_mismatch() -> None:
    state = create_state()
    context = create_context(state)
    draft = AssembledInvoiceDraft(
        document_id=state.document_id,
        groups=InvoiceExtractionGroups(
            metadata=InvoiceMetadataGroup(invoice_number="INV-002"),
            table=InvoiceTableGroup(
                extraction_status=InvoiceExtractionStatus.EXTRACTED,
                line_items=[
                    InvoiceLineItemCandidate(
                        line_number=1,
                        description="Service",
                        line_total="80.00",
                    )
                ],
            ),
            totals=InvoiceTotalsGroup(
                extraction_status=InvoiceExtractionStatus.EXTRACTED,
                subtotal_amount="100.00",
                tax_amount="10.00",
                total_amount="110.00",
            ),
        ),
        assembly_status=InvoiceExtractionStatus.EXTRACTED,
    )
    state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY] = draft.model_dump(mode="json")

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.REVIEW_REQUIRED
    assert any(
        signal.code == "ERR_SUBTOTAL_LINE_ITEMS_MISMATCH"
        for signal in result.qa_error_signals
    )


@pytest.mark.asyncio
async def test_qa_validation_agent_flags_party_role_confusion() -> None:
    state = create_state()
    context = create_context(state)
    draft = AssembledInvoiceDraft(
        document_id=state.document_id,
        groups=InvoiceExtractionGroups(
            metadata=InvoiceMetadataGroup(
                invoice_number="INV-ROLE-001",
                supplier_name="John Sample",
                customer_name="Service Demo Autocare Ltd",
            ),
            table=InvoiceTableGroup(),
            totals=InvoiceTotalsGroup(),
        ),
        assembly_status=InvoiceExtractionStatus.EXTRACTED,
    )
    state.scratchpad[ASSEMBLED_INVOICE_DRAFT_KEY] = draft.model_dump(mode="json")
    state.scratchpad[OCR_LAYOUT_REGIONS_KEY] = {
        "supplier": {
            "region_type": "supplier",
            "block_ids": ["ocr:block:1"],
            "text": "Service Demo Autocare Ltd\nHorton Park Ave\nBradford",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        },
        "bill_to": {
            "region_type": "bill_to",
            "block_ids": ["ocr:block:8"],
            "text": "Bill to:\nJohn Sample\n7 Example Road",
            "bounding_box": None,
            "confidence": None,
            "source": "ocr_layout_blocks",
        },
    }

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.REVIEW_REQUIRED
    assert any(
        signal.code == "ERR_PARTY_ROLE_CONFUSION" for signal in result.qa_error_signals
    )


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


@pytest.mark.asyncio
async def test_qa_validation_agent_routes_to_review_required_for_blocking_signal() -> (
    None
):
    """QA returns REVIEW_REQUIRED when a non-retryable BLOCKING signal is present.

    This is the failure path routed by record_provider_extraction_error when a
    provider produces invalid or missing output.
    """
    from app.workflows.contracts import QAErrorSeverity, QAErrorSignal

    state = create_state()
    context = create_context(state)
    blocking_signal = QAErrorSignal(
        code="ERR_LLM_PROVIDER_FAILED",
        severity=QAErrorSeverity.BLOCKING,
        message=(
            "Metadata extractor provider extraction failed and requires human review."
        ),
        source_agent=METADATA_EXTRACTOR_AGENT,
        retryable=False,
    )
    state.qa_error_signals.append(blocking_signal)

    result = await QAValidationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.REVIEW_REQUIRED
    assert result.output["validation_status"] == "review_required"
    assert result.output["qa_error_count"] == 1
    assert result.qa_error_signals == [blocking_signal]
    assert result.handoffs == []


@pytest.mark.asyncio
async def test_extractor_emits_blocking_signal_on_bad_provider_schema() -> None:
    """When the LLM returns a schema-invalid shape, a blocking QA signal is added.

    This covers Task 1: failure path when provider output fails validation.  Even
    though the extractor succeeds via OCR fallback, the blocking QA signal ensures
    QA routes the workflow to REVIEW_REQUIRED for human review.
    """
    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = COMMON_INVOICE_OCR_TEXT
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=InvalidStructuredOutputLLMProvider(),
    )

    result = await MetadataExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=METADATA_EXTRACTOR_AGENT,
            stage=WorkflowStage.METADATA_EXTRACTION,
        ),
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    assert PROVIDER_EXTRACTION_ERRORS_KEY in state.scratchpad
    # A blocking, non-retryable QA signal must be present so QA can route to
    # REVIEW_REQUIRED even though the extractor itself returned SUCCEEDED.
    assert len(state.qa_error_signals) == 1
    qa_signal = state.qa_error_signals[0]
    assert qa_signal.severity.value == "blocking"
    assert qa_signal.retryable is False
    assert qa_signal.source_agent == METADATA_EXTRACTOR_AGENT


@pytest.mark.asyncio
async def test_extractor_emits_blocking_signal_when_provider_call_fails() -> None:
    """When the LLM provider raises a ProviderError, a blocking QA signal is added.

    This covers Task 2: fallback to review-required state when provider fails.
    The extractor falls back to OCR text but the blocking signal ensures QA routes
    to REVIEW_REQUIRED rather than silently completing with partial data.
    """
    from app.providers.errors import ProviderExecutionError

    class FailingLLMProvider:
        @property
        def name(self) -> str:
            return "failing_llm"

        async def generate(
            self,
            *,
            request: LLMGenerationRequest,
            context: LLMProviderRunContext,
        ) -> LLMGenerationResult:
            del request, context
            raise ProviderExecutionError("LLM service unavailable.")

    state = create_state()
    state.scratchpad[OCR_FULL_TEXT_KEY] = COMMON_INVOICE_OCR_TEXT
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        llm_provider=FailingLLMProvider(),
    )

    result = await MetadataExtractorAgent().run(
        state=state,
        context=context,
        handoff=create_layout_handoff(
            state=state,
            target_agent=METADATA_EXTRACTOR_AGENT,
            stage=WorkflowStage.METADATA_EXTRACTION,
        ),
    )

    assert result.status == AgentRunStatus.SUCCEEDED
    assert PROVIDER_EXTRACTION_ERRORS_KEY in state.scratchpad
    assert len(state.qa_error_signals) == 1
    qa_signal = state.qa_error_signals[0]
    assert qa_signal.severity.value == "blocking"
    assert qa_signal.retryable is False
    assert qa_signal.source_agent == METADATA_EXTRACTOR_AGENT
    assert "ERR_LLM_PROVIDER_FAILED" in qa_signal.code
