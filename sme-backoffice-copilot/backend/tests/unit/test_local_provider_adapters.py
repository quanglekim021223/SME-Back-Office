from collections.abc import Sequence
from subprocess import CompletedProcess
from uuid import uuid4

import pytest

from app.providers import (
    LLMGenerationRequest,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
    OCRInput,
    OCRProvider,
    OCRProviderRunContext,
    OllamaLLMProvider,
    PaddleOCRProvider,
    ProviderConfigurationError,
    ProviderDependencyError,
    ProviderExecutionError,
    TesseractOCRProvider,
)
from app.providers.ollama import build_ollama_chat_payload


def create_ocr_context() -> OCRProviderRunContext:
    return OCRProviderRunContext(
        tenant_id=uuid4(),
        document_id=uuid4(),
        workflow_run_id=uuid4(),
        correlation_id="corr-123",
    )


@pytest.mark.asyncio
async def test_tesseract_provider_runs_configured_binary() -> None:
    captured_command: list[str] = []

    def fake_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CompletedProcess[str]:
        captured_command.extend(command)
        assert timeout_seconds == 15.0
        return CompletedProcess(
            args=list(command),
            returncode=0,
            stdout="Invoice #INV-001\nTotal 110.00\n",
            stderr="",
        )

    provider = TesseractOCRProvider(
        binary_path="/opt/homebrew/bin/tesseract",
        language="eng+vie",
        timeout_seconds=15.0,
        runner=fake_runner,
    )

    assert isinstance(provider, OCRProvider)

    result = await provider.extract_text(
        input_data=OCRInput(
            artifact_uri="local://document/original.png",
            media_type="image/png",
            content_hash="hash-123",
            local_path="/tmp/original.png",
        ),
        context=create_ocr_context(),
    )

    assert captured_command == [
        "/opt/homebrew/bin/tesseract",
        "/tmp/original.png",
        "stdout",
        "-l",
        "eng+vie",
    ]
    assert result.provider_name == "tesseract"
    assert result.full_text == "Invoice #INV-001\nTotal 110.00"
    assert [block.text for block in result.text_blocks] == [
        "Invoice #INV-001",
        "Total 110.00",
    ]
    assert result.metadata["command"] == captured_command


@pytest.mark.asyncio
async def test_tesseract_provider_requires_local_path() -> None:
    provider = TesseractOCRProvider()

    with pytest.raises(ProviderConfigurationError):
        await provider.extract_text(
            input_data=OCRInput(artifact_uri="local://document/original.png"),
            context=create_ocr_context(),
        )


@pytest.mark.asyncio
async def test_tesseract_provider_reports_missing_binary() -> None:
    def missing_binary_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CompletedProcess[str]:
        del command, timeout_seconds
        raise FileNotFoundError

    provider = TesseractOCRProvider(runner=missing_binary_runner)

    with pytest.raises(ProviderDependencyError):
        await provider.extract_text(
            input_data=OCRInput(
                artifact_uri="local://document/original.png",
                local_path="/tmp/original.png",
            ),
            context=create_ocr_context(),
        )


@pytest.mark.asyncio
async def test_tesseract_provider_reports_failed_command() -> None:
    def failing_runner(
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CompletedProcess[str]:
        del timeout_seconds
        return CompletedProcess(
            args=list(command),
            returncode=1,
            stdout="",
            stderr="bad image",
        )

    provider = TesseractOCRProvider(runner=failing_runner)

    with pytest.raises(ProviderExecutionError):
        await provider.extract_text(
            input_data=OCRInput(
                artifact_uri="local://document/original.png",
                local_path="/tmp/original.png",
            ),
            context=create_ocr_context(),
        )


class FakePaddleEngine:
    def ocr(self, local_path: str) -> object:
        assert local_path == "/tmp/original.png"
        return [
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], ("Invoice #INV-001", 0.98)],
                [[[0, 30], [100, 30], [100, 50], [0, 50]], ("Total 110.00", 0.96)],
            ]
        ]


@pytest.mark.asyncio
async def test_paddleocr_provider_normalizes_common_output_shape() -> None:
    provider = PaddleOCRProvider(language="en", engine=FakePaddleEngine())

    assert isinstance(provider, OCRProvider)

    result = await provider.extract_text(
        input_data=OCRInput(
            artifact_uri="local://document/original.png",
            media_type="image/png",
            content_hash="hash-123",
            local_path="/tmp/original.png",
        ),
        context=create_ocr_context(),
    )

    assert result.provider_name == "paddleocr"
    assert result.full_text == "Invoice #INV-001\nTotal 110.00"
    assert len(result.text_blocks) == 2
    assert result.text_blocks[0].bounding_box == [
        0.0,
        0.0,
        100.0,
        0.0,
        100.0,
        20.0,
        0.0,
        20.0,
    ]
    assert result.confidence == pytest.approx(0.97)


@pytest.mark.asyncio
async def test_paddleocr_provider_requires_local_path() -> None:
    provider = PaddleOCRProvider(engine=FakePaddleEngine())

    with pytest.raises(ProviderConfigurationError):
        await provider.extract_text(
            input_data=OCRInput(artifact_uri="local://document/original.png"),
            context=create_ocr_context(),
        )


@pytest.mark.asyncio
async def test_ollama_provider_builds_chat_request_and_parses_json() -> None:
    captured_endpoint = ""
    captured_payload: dict[str, object] = {}

    def fake_transport(
        endpoint: str,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        nonlocal captured_endpoint, captured_payload
        assert timeout_seconds == 20.0
        captured_endpoint = endpoint
        captured_payload = payload
        return {
            "message": {
                "role": "assistant",
                "content": '{"invoice_number":"INV-001","total_amount":"110.00"}',
            },
            "prompt_eval_count": 12,
            "eval_count": 8,
            "total_duration": 25_000_000,
        }

    provider = OllamaLLMProvider(
        base_url="http://localhost:11434/",
        model_name="llama3.1:8b",
        timeout_seconds=20.0,
        transport=fake_transport,
    )

    assert isinstance(provider, LLMProvider)

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Extract invoice JSON.",
                )
            ],
            response_format=LLMResponseFormat.JSON,
            response_schema_name="invoice-metadata-group.v1",
            max_output_tokens=512,
        ),
        context=LLMProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
            agent_name="metadata_extractor",
        ),
    )

    assert captured_endpoint == "http://localhost:11434/api/chat"
    assert captured_payload["model"] == "llama3.1:8b"
    assert captured_payload["format"] == "json"
    assert captured_payload["stream"] is False
    assert captured_payload["options"] == {
        "temperature": 0.0,
        "num_predict": 512,
    }
    assert result.provider_name == "ollama"
    assert result.model_name == "llama3.1:8b"
    assert result.structured_output == {
        "invoice_number": "INV-001",
        "total_amount": "110.00",
    }
    assert result.input_tokens == 12
    assert result.output_tokens == 8
    assert result.latency_ms == 25


def test_ollama_payload_omits_json_format_for_text_responses() -> None:
    payload = build_ollama_chat_payload(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Summarize invoice.",
                )
            ],
            response_format=LLMResponseFormat.TEXT,
        ),
        model_name="llama3.1:8b",
    )

    assert "format" not in payload


@pytest.mark.asyncio
async def test_ollama_provider_reports_transport_errors() -> None:
    def failing_transport(
        endpoint: str,
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        del endpoint, payload, timeout_seconds
        raise OSError("connection refused")

    provider = OllamaLLMProvider(transport=failing_transport)

    with pytest.raises(ProviderExecutionError):
        await provider.generate(
            request=LLMGenerationRequest(
                messages=[
                    LLMMessage(
                        role=LLMMessageRole.USER,
                        content="Extract invoice JSON.",
                    )
                ],
            ),
            context=LLMProviderRunContext(tenant_id=uuid4()),
        )
