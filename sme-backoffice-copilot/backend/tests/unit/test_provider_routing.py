import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.providers import (
    LLMGenerationRequest,
    LLMMessage,
    LLMMessageRole,
    LLMProviderRunContext,
    LLMResponseFormat,
    MockLLMProvider,
    MockOCRProvider,
    OCRInput,
    OCRProviderRunContext,
    ProviderExecutionError,
    ProviderRouteKind,
    ProviderRuntime,
    ProviderTaskType,
    build_default_provider_routing_config,
)


class FlakyMockLLMProvider(MockLLMProvider):
    def __init__(self, *, failures_before_success: int) -> None:
        super().__init__()
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise ProviderExecutionError("Temporary mock provider failure.")
        return await super().generate(**kwargs)


class SlowMockLLMProvider(MockLLMProvider):
    async def generate(self, **kwargs):
        await asyncio.sleep(0.05)
        return await super().generate(**kwargs)


@pytest.mark.asyncio
async def test_provider_runtime_routes_mock_llm_with_cost_tracking() -> None:
    routing_config = build_default_provider_routing_config(
        llm_input_cost_per_1k_tokens=Decimal("0.0100"),
        llm_output_cost_per_1k_tokens=Decimal("0.0200"),
    )
    runtime = ProviderRuntime(routing_config)
    provider = MockLLMProvider()

    invocation = await runtime.generate_llm(
        provider=provider,
        task_type=ProviderTaskType.INVOICE_METADATA_EXTRACTION,
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Extract invoice metadata from mock OCR text.",
                )
            ],
            response_format=LLMResponseFormat.JSON,
        ),
        context=LLMProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
            agent_name="metadata_extractor",
        ),
    )

    assert invocation.route.provider_name == "mock_llm"
    assert invocation.route.prompt_id == "invoice.metadata_extraction"
    assert invocation.route.response_schema_name == "invoice-metadata-group.v1"
    assert invocation.result.structured_output is not None
    assert invocation.result.structured_output["invoice_number"] == "INV-MOCK-001"
    assert invocation.result.metadata["prompt_id"] == "invoice.metadata_extraction"
    assert invocation.attempts == 1
    assert invocation.cost.input_tokens == invocation.result.input_tokens
    assert invocation.cost.output_tokens == invocation.result.output_tokens
    assert invocation.cost.total_cost > Decimal("0")
    assert invocation.cost.currency == "USD"


@pytest.mark.asyncio
async def test_provider_runtime_routes_mock_ocr() -> None:
    routing_config = build_default_provider_routing_config()
    runtime = ProviderRuntime(routing_config)
    provider = MockOCRProvider()

    invocation = await runtime.extract_ocr(
        provider=provider,
        task_type=ProviderTaskType.DOCUMENT_OCR,
        input_data=OCRInput(
            artifact_uri="local://tenant/document/invoice.pdf",
            content_hash="hash-123",
        ),
        context=OCRProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
        ),
    )

    assert invocation.route.route_kind == ProviderRouteKind.OCR
    assert invocation.route.provider_name == "mock_ocr"
    assert invocation.result.provider_name == "mock_ocr"
    assert invocation.result.text_blocks
    assert invocation.attempts == 1


@pytest.mark.asyncio
async def test_provider_runtime_retries_transient_provider_failure() -> None:
    routing_config = build_default_provider_routing_config(max_retries=2)
    runtime = ProviderRuntime(routing_config)
    provider = FlakyMockLLMProvider(failures_before_success=1)

    invocation = await runtime.generate_llm(
        provider=provider,
        task_type=ProviderTaskType.INVOICE_TOTALS_EXTRACTION,
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Extract invoice totals.",
                )
            ],
            response_format=LLMResponseFormat.JSON,
        ),
        context=LLMProviderRunContext(tenant_id=uuid4()),
    )

    assert provider.calls == 2
    assert invocation.attempts == 2
    assert invocation.result.structured_output is not None
    assert invocation.result.structured_output["total_amount"] == "110.00"


@pytest.mark.asyncio
async def test_provider_runtime_raises_after_retry_exhaustion() -> None:
    routing_config = build_default_provider_routing_config(max_retries=1)
    runtime = ProviderRuntime(routing_config)
    provider = FlakyMockLLMProvider(failures_before_success=3)

    with pytest.raises(ProviderExecutionError, match="failed after 2 attempt"):
        await runtime.generate_llm(
            provider=provider,
            task_type=ProviderTaskType.INVOICE_TABLE_EXTRACTION,
            request=LLMGenerationRequest(
                messages=[
                    LLMMessage(
                        role=LLMMessageRole.USER,
                        content="Extract invoice table.",
                    )
                ],
                response_format=LLMResponseFormat.JSON,
            ),
            context=LLMProviderRunContext(tenant_id=uuid4()),
        )

    assert provider.calls == 2


@pytest.mark.asyncio
async def test_provider_runtime_applies_timeout_policy() -> None:
    routing_config = build_default_provider_routing_config(
        timeout_seconds=0.001,
        max_retries=0,
    )
    runtime = ProviderRuntime(routing_config)
    provider = SlowMockLLMProvider()

    with pytest.raises(ProviderExecutionError, match="failed after 1 attempt"):
        await runtime.generate_llm(
            provider=provider,
            task_type=ProviderTaskType.INVOICE_CLASSIFICATION,
            request=LLMGenerationRequest(
                messages=[
                    LLMMessage(
                        role=LLMMessageRole.USER,
                        content="Classify invoice.",
                    )
                ],
                response_format=LLMResponseFormat.JSON,
            ),
            context=LLMProviderRunContext(tenant_id=uuid4()),
        )


def test_provider_routing_config_reports_missing_route() -> None:
    routing_config = build_default_provider_routing_config()

    with pytest.raises(ProviderExecutionError, match="No provider route configured"):
        routing_config.route_for(ProviderTaskType.BUSINESS_INSIGHT_GENERATION)
