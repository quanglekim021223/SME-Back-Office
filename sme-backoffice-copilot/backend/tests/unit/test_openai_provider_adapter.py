from uuid import uuid4

import pytest

from app.providers import (
    LLMGenerationRequest,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
    OpenAIResponsesLLMProvider,
    ProviderConfigurationError,
    ProviderExecutionError,
)
from app.providers.openai import (
    build_openai_responses_payload,
    extract_openai_output_text,
)


@pytest.mark.asyncio
async def test_openai_provider_builds_responses_request_and_parses_json() -> None:
    captured_endpoint = ""
    captured_payload: dict[str, object] = {}
    captured_api_key = ""

    def fake_transport(
        endpoint: str,
        payload: dict[str, object],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        nonlocal captured_endpoint, captured_payload, captured_api_key
        assert timeout_seconds == 20.0
        captured_endpoint = endpoint
        captured_payload = payload
        captured_api_key = api_key
        return {
            "id": "resp_test_123",
            "status": "completed",
            "model": "gpt-5.2",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"invoice_number":"INV-OPENAI-001",'
                                '"total_amount":"110.00"}'
                            ),
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": 42,
                "output_tokens": 13,
                "total_tokens": 55,
            },
        }

    provider = OpenAIResponsesLLMProvider(
        api_key="test-key",
        base_url="https://api.openai.test/v1/",
        model_name="gpt-5.2",
        timeout_seconds=20.0,
        transport=fake_transport,
    )

    assert isinstance(provider, LLMProvider)

    result = await provider.generate(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content="Return compact invoice JSON only.",
                ),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content="Extract invoice metadata.",
                ),
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

    assert captured_endpoint == "https://api.openai.test/v1/responses"
    assert captured_api_key == "test-key"
    assert captured_payload["model"] == "gpt-5.2"
    assert captured_payload["instructions"] == "Return compact invoice JSON only."
    assert captured_payload["max_output_tokens"] == 512
    assert captured_payload["text"] == {"format": {"type": "json_object"}}
    assert captured_payload["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Extract invoice metadata."}],
        }
    ]
    assert result.provider_name == "openai"
    assert result.model_name == "gpt-5.2"
    assert result.structured_output == {
        "invoice_number": "INV-OPENAI-001",
        "total_amount": "110.00",
    }
    assert result.input_tokens == 42
    assert result.output_tokens == 13
    assert result.metadata["response_id"] == "resp_test_123"


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ProviderConfigurationError):
        OpenAIResponsesLLMProvider(api_key="")


def test_openai_payload_supports_text_responses_and_system_only_messages() -> None:
    payload = build_openai_responses_payload(
        request=LLMGenerationRequest(
            messages=[
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content="Summarize the invoice.",
                )
            ],
            response_format=LLMResponseFormat.TEXT,
        ),
        model_name="gpt-5.2",
    )

    assert payload["instructions"] == "Summarize the invoice."
    assert payload["input"] == "Respond according to the instructions."
    assert payload["text"] == {"format": {"type": "text"}}


def test_openai_output_text_extraction_supports_top_level_output_text() -> None:
    assert extract_openai_output_text({"output_text": "hello"}) == "hello"


@pytest.mark.asyncio
async def test_openai_provider_reports_response_errors() -> None:
    def fake_transport(
        endpoint: str,
        payload: dict[str, object],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        del endpoint, payload, api_key, timeout_seconds
        return {
            "id": "resp_failed",
            "status": "failed",
            "error": {"message": "bad request"},
        }

    provider = OpenAIResponsesLLMProvider(
        api_key="test-key",
        transport=fake_transport,
    )

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
