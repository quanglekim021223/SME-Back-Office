from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import LLMProviderType, OCRProviderType, Settings
from app.providers import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
    OCRInput,
    OCRProvider,
    OCRProviderRunContext,
    OCRResult,
    OCRTextBlock,
)


class FakeOCRProvider:
    @property
    def name(self) -> str:
        return "fake_ocr"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        return OCRResult(
            provider_name=self.name,
            provider_version="0.1.0",
            language="en",
            full_text=f"Extracted from {input_data.artifact_uri}",
            text_blocks=[
                OCRTextBlock(
                    text="Invoice #INV-001",
                    page_number=1,
                    confidence=0.99,
                )
            ],
            confidence=0.99,
            metadata={"tenant_id": str(context.tenant_id)},
        )


class FakeLLMProvider:
    @property
    def name(self) -> str:
        return "fake_llm"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        return LLMGenerationResult(
            provider_name=self.name,
            model_name="fake-model",
            output_text='{"invoice_number": "INV-001"}',
            structured_output={
                "invoice_number": "INV-001",
                "agent_name": context.agent_name,
                "message_count": len(request.messages),
            },
            input_tokens=10,
            output_tokens=5,
            latency_ms=1,
        )


def test_settings_include_ai_provider_selection_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.ocr_provider == OCRProviderType.MOCK
    assert settings.llm_provider == LLMProviderType.MOCK
    assert settings.provider_timeout_seconds == 30.0
    assert settings.tesseract_binary_path == "tesseract"
    assert settings.tesseract_language == "eng"
    assert settings.paddleocr_language == "en"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "llama3.1:8b"


def test_settings_can_select_local_free_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "paddleocr")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:7b")

    settings = Settings(_env_file=None)

    assert settings.ocr_provider == OCRProviderType.PADDLEOCR
    assert settings.llm_provider == LLMProviderType.OLLAMA
    assert settings.ollama_model == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_ocr_provider_interface_contract() -> None:
    provider = FakeOCRProvider()
    tenant_id = uuid4()
    document_id = uuid4()

    assert isinstance(provider, OCRProvider)

    result = await provider.extract_text(
        input_data=OCRInput(
            artifact_uri="local://tenants/t/documents/d/original/invoice.pdf",
            media_type="application/pdf",
            content_hash="hash-123",
        ),
        context=OCRProviderRunContext(
            tenant_id=tenant_id,
            document_id=document_id,
            correlation_id="corr-123",
        ),
    )

    assert result.provider_name == "fake_ocr"
    assert result.full_text.startswith("Extracted from local://")
    assert result.text_blocks[0].text == "Invoice #INV-001"
    assert result.model_dump(mode="json")["metadata"]["tenant_id"] == str(tenant_id)


def test_ocr_contract_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        OCRTextBlock(
            text="Invalid confidence",
            confidence=1.5,
        )


@pytest.mark.asyncio
async def test_llm_provider_interface_contract() -> None:
    provider = FakeLLMProvider()
    tenant_id = uuid4()

    assert isinstance(provider, LLMProvider)

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content="Extract invoice JSON.",
                ),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Invoice #INV-001",
                ),
            ],
            response_format=LLMResponseFormat.JSON,
            response_schema_name="invoice-metadata-group.v1",
        ),
        context=LLMProviderRunContext(
            tenant_id=tenant_id,
            agent_name="metadata_extractor",
            correlation_id="corr-123",
        ),
    )

    assert result.provider_name == "fake_llm"
    assert result.model_name == "fake-model"
    assert result.structured_output is not None
    assert result.structured_output["invoice_number"] == "INV-001"
    assert result.structured_output["agent_name"] == "metadata_extractor"


def test_llm_contract_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        LLMGenerationRequest(messages=[])
