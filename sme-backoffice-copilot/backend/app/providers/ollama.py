"""Optional local LLM provider adapter for Ollama."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import Callable
from typing import cast

from app.providers.errors import ProviderExecutionError
from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderRunContext,
    LLMResponseFormat,
)
from app.providers.structured_output import validate_structured_output

OllamaTransport = Callable[[str, dict[str, object], float], dict[str, object]]


def urlopen_ollama_transport(
    endpoint: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    """Call the Ollama HTTP API using Python standard library."""

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return cast(dict[str, object], json.loads(response.read().decode("utf-8")))


class OllamaLLMProvider:
    """LLM provider adapter backed by a local Ollama server."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model_name: str = "llama3.1:8b",
        timeout_seconds: float = 30.0,
        transport: OllamaTransport = urlopen_ollama_transport,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def name(self) -> str:
        """Return the stable Ollama provider name."""

        return "ollama"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        """Generate text or structured JSON through Ollama's local API."""

        endpoint = f"{self.base_url}/api/chat"
        payload = build_ollama_chat_payload(
            request=request,
            model_name=self.model_name,
        )
        try:
            response_payload = await asyncio.to_thread(
                self.transport,
                endpoint,
                payload,
                self.timeout_seconds,
            )
        except OSError as exc:
            raise ProviderExecutionError(
                "Could not call Ollama. Ensure Ollama is running locally and "
                f"reachable at {self.base_url}."
            ) from exc

        output_text = extract_ollama_output_text(response_payload)
        structured_output = parse_structured_output(
            output_text=output_text,
            response_format=request.response_format,
        )
        metadata: dict[str, object] = {
            "base_url": self.base_url,
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
        return LLMGenerationResult(
            provider_name=self.name,
            model_name=self.model_name,
            output_text=output_text,
            structured_output=structured_output,
            input_tokens=int_or_none(response_payload.get("prompt_eval_count")),
            output_tokens=int_or_none(response_payload.get("eval_count")),
            latency_ms=duration_ns_to_ms(response_payload.get("total_duration")),
            metadata=metadata,
        )


def build_ollama_chat_payload(
    *,
    request: LLMGenerationRequest,
    model_name: str,
) -> dict[str, object]:
    """Build an Ollama /api/chat request payload."""

    options: dict[str, object] = {"temperature": request.temperature}
    if request.max_output_tokens is not None:
        options["num_predict"] = request.max_output_tokens

    payload: dict[str, object] = {
        "model": model_name,
        "messages": [
            {"role": message.role.value, "content": message.content}
            for message in request.messages
        ],
        "stream": False,
        "options": options,
    }
    if request.response_format == LLMResponseFormat.JSON:
        payload["format"] = "json"
    return payload


def extract_ollama_output_text(response_payload: dict[str, object]) -> str:
    """Extract assistant text from an Ollama response payload."""

    message = response_payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    response = response_payload.get("response")
    if isinstance(response, str):
        return response
    raise ProviderExecutionError("Ollama response did not include model output text.")


def parse_structured_output(
    *,
    output_text: str,
    response_format: LLMResponseFormat,
) -> dict[str, object] | None:
    """Parse JSON output for structured generation requests."""

    if response_format != LLMResponseFormat.JSON:
        return None
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def int_or_none(value: object) -> int | None:
    """Return an integer when value is numeric."""

    return value if isinstance(value, int) else None


def duration_ns_to_ms(value: object) -> int | None:
    """Convert Ollama nanosecond duration values into milliseconds."""

    if not isinstance(value, int):
        return None
    return int(value / 1_000_000)
