from uuid import uuid4

import pytest

from app.providers import (
    DEFAULT_MOCK_OCR_TEXT,
    LLMGenerationRequest,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
    MockLLMProvider,
    MockOCRProvider,
    OCRInput,
    OCRProvider,
    OCRProviderRunContext,
)


@pytest.mark.asyncio
async def test_mock_ocr_provider_returns_deterministic_text_blocks() -> None:
    provider = MockOCRProvider()
    tenant_id = uuid4()
    document_id = uuid4()

    assert isinstance(provider, OCRProvider)

    result = await provider.extract_text(
        input_data=OCRInput(
            artifact_uri="local://tenant/document/original.pdf",
            media_type="application/pdf",
            content_hash="hash-123",
        ),
        context=OCRProviderRunContext(
            tenant_id=tenant_id,
            document_id=document_id,
            correlation_id="corr-123",
        ),
    )

    assert result.provider_name == "mock_ocr"
    assert result.full_text == DEFAULT_MOCK_OCR_TEXT
    assert result.text_blocks[0].text == "Invoice #INV-MOCK-001"
    assert result.confidence == 0.99
    assert result.metadata["tenant_id"] == str(tenant_id)
    assert result.metadata["document_id"] == str(document_id)
    assert result.metadata["correlation_id"] == "corr-123"


@pytest.mark.asyncio
async def test_mock_ocr_provider_allows_per_call_text_override() -> None:
    provider = MockOCRProvider()

    result = await provider.extract_text(
        input_data=OCRInput(
            artifact_uri="local://tenant/document/custom.pdf",
            metadata={"mock_full_text": "Custom invoice text"},
        ),
        context=OCRProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
        ),
    )

    assert result.full_text == "Custom invoice text"
    assert len(result.text_blocks) == 1
    assert result.text_blocks[0].text == "Custom invoice text"


@pytest.mark.asyncio
async def test_mock_llm_provider_returns_schema_specific_json() -> None:
    provider = MockLLMProvider()

    assert isinstance(provider, LLMProvider)

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Extract invoice metadata from mock OCR text.",
                )
            ],
            response_format=LLMResponseFormat.JSON,
            response_schema_name="invoice-metadata-group.v1",
        ),
        context=LLMProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
            agent_name="metadata_extractor",
        ),
    )

    assert result.provider_name == "mock_llm"
    assert result.model_name == "mock-llm"
    assert result.structured_output is not None
    assert result.structured_output["invoice_number"] == "INV-MOCK-001"
    assert result.structured_output["supplier_name"] == "Mock Supplier Ltd"
    assert result.output_text.startswith("{")
    assert result.input_tokens is not None
    assert result.output_tokens is not None
    assert result.metadata["response_schema_name"] == "invoice-metadata-group.v1"
    validation = result.metadata["structured_output_validation"]
    assert isinstance(validation, dict)
    assert validation["passed"] is True
    assert validation["schema_registered"] is True


@pytest.mark.asyncio
async def test_mock_llm_provider_returns_generic_json_for_unknown_schema() -> None:
    provider = MockLLMProvider()

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Generate custom JSON.",
                )
            ],
            response_format=LLMResponseFormat.JSON,
            response_schema_name="custom-schema.v1",
        ),
        context=LLMProviderRunContext(
            tenant_id=uuid4(),
            agent_name="custom_agent",
        ),
    )

    assert result.structured_output == {
        "schema_version": "custom-schema.v1",
        "mock": True,
        "agent_name": "custom_agent",
        "message_count": 1,
    }


@pytest.mark.asyncio
async def test_mock_llm_provider_can_return_text_response() -> None:
    provider = MockLLMProvider()

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Summarize the invoice.",
                )
            ],
            response_format=LLMResponseFormat.TEXT,
            response_schema_name="invoice-summary.v1",
        ),
        context=LLMProviderRunContext(tenant_id=uuid4()),
    )

    assert result.output_text == "Mock LLM response for invoice-summary.v1."
    assert result.structured_output is None
    assert result.metadata["response_format"] == LLMResponseFormat.TEXT.value
