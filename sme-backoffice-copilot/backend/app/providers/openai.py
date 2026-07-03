"""Optional cloud LLM provider adapter for OpenAI Responses API."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import cast

from app.providers.errors import ProviderConfigurationError, ProviderExecutionError
from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMMessage,
    LLMMessageRole,
    LLMProviderRunContext,
    LLMResponseFormat,
)
from app.providers.ollama import parse_structured_output
from app.providers.structured_output import validate_structured_output

OpenAITransport = Callable[
    [str, dict[str, object], str, float],
    dict[str, object],
]


def urlopen_openai_transport(
    endpoint: str,
    payload: dict[str, object],
    api_key: str,
    timeout_seconds: float,
) -> dict[str, object]:
    """Call the OpenAI Responses API using Python standard library."""

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return cast(
                dict[str, object],
                json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ProviderExecutionError(
            f"OpenAI request failed with HTTP {exc.code}: {error_body}"
        ) from exc


class OpenAIResponsesLLMProvider:
    """LLM provider adapter backed by OpenAI's Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-5.2",
        timeout_seconds: float = 30.0,
        transport: OpenAITransport = urlopen_openai_transport,
    ) -> None:
        if not api_key:
            raise ProviderConfigurationError("OpenAI API key is required.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def name(self) -> str:
        """Return the stable OpenAI provider name."""

        return "openai"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        """Generate text or structured JSON through OpenAI Responses API."""

        endpoint = f"{self.base_url}/responses"
        payload = build_openai_responses_payload(
            request=request,
            model_name=self.model_name,
        )
        try:
            response_payload = await asyncio.to_thread(
                self.transport,
                endpoint,
                payload,
                self.api_key,
                self.timeout_seconds,
            )
        except OSError as exc:
            raise ProviderExecutionError(
                "Could not call OpenAI Responses API. Check network access, "
                "API key, and provider routing configuration."
            ) from exc

        raise_for_openai_response_error(response_payload)
        output_text = extract_openai_output_text(response_payload)
        structured_output = parse_structured_output(
            output_text=output_text,
            response_format=request.response_format,
        )
        metadata: dict[str, object] = {
            "base_url": self.base_url,
            "response_id": response_payload.get("id"),
            "response_status": response_payload.get("status"),
            "response_schema_name": request.response_schema_name,
            "response_format": request.response_format.value,
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "agent_name": context.agent_name,
            "tenant_id": str(context.tenant_id),
            "document_id": str(context.document_id)
            if context.document_id is not None
            else None,
            "workflow_run_id": str(context.workflow_run_id)
            if context.workflow_run_id is not None
            else None,
            "correlation_id": context.correlation_id,
        }
        if structured_output is not None and request.response_schema_name is not None:
            metadata["structured_output_validation"] = validate_structured_output(
                schema_name=request.response_schema_name,
                payload=structured_output,
            ).model_dump(mode="json")

        usage = response_payload.get("usage")
        return LLMGenerationResult(
            provider_name=self.name,
            model_name=str(response_payload.get("model") or self.model_name),
            output_text=output_text,
            structured_output=structured_output,
            input_tokens=usage_token_count(usage, "input_tokens"),
            output_tokens=usage_token_count(usage, "output_tokens"),
            latency_ms=None,
            metadata=metadata,
        )


def build_openai_responses_payload(
    *,
    request: LLMGenerationRequest,
    model_name: str,
) -> dict[str, object]:
    """Build an OpenAI /v1/responses request payload."""

    system_messages = [
        message.content
        for message in request.messages
        if message.role == LLMMessageRole.SYSTEM
    ]
    input_messages = [
        openai_input_message(message)
        for message in request.messages
        if message.role != LLMMessageRole.SYSTEM
    ]

    payload: dict[str, object] = {
        "model": model_name,
        "input": input_messages or "Respond according to the instructions.",
        "temperature": request.temperature,
        "text": {
            "format": {
                "type": "json_object"
                if request.response_format == LLMResponseFormat.JSON
                else "text",
            }
        },
    }
    if system_messages:
        payload["instructions"] = "\n\n".join(system_messages)
    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens
    return payload


def openai_input_message(message: LLMMessage) -> dict[str, object]:
    """Convert a provider-neutral LLM message into a Responses API input item."""

    return {
        "role": "assistant" if message.role == LLMMessageRole.ASSISTANT else "user",
        "content": [{"type": "input_text", "text": message.content}],
    }


def raise_for_openai_response_error(response_payload: dict[str, object]) -> None:
    """Raise if the OpenAI response object contains an API error."""

    error = response_payload.get("error")
    if error is not None:
        raise ProviderExecutionError(f"OpenAI response returned an error: {error}")
    status = response_payload.get("status")
    if status in {"failed", "cancelled", "incomplete"}:
        raise ProviderExecutionError(f"OpenAI response status was {status}.")


def extract_openai_output_text(response_payload: dict[str, object]) -> str:
    """Extract assistant output text from a raw OpenAI Responses API payload."""

    output_text = response_payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    output_items = response_payload.get("output")
    if not isinstance(output_items, list):
        raise ProviderExecutionError("OpenAI response did not include output items.")

    chunks: list[str] = []
    for output_item in output_items:
        if not isinstance(output_item, dict):
            continue
        content_items = output_item.get("content")
        if not isinstance(content_items, list):
            continue
        chunks.extend(extract_text_chunks(content_items))

    if not chunks:
        raise ProviderExecutionError("OpenAI response did not include output text.")
    return "\n".join(chunks)


def extract_text_chunks(content_items: list[object]) -> list[str]:
    """Extract text chunks from Responses API message content items."""

    chunks: list[str] = []
    for content_item in content_items:
        if not isinstance(content_item, dict):
            continue
        text = content_item.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return chunks


def usage_token_count(usage: object, key: str) -> int | None:
    """Extract token count from OpenAI usage object."""

    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    return value if isinstance(value, int) else None
