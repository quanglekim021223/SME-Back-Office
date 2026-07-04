"""LLM provider interface and shared generation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LLMMessageRole(StrEnum):
    """Supported chat message roles for provider-neutral LLM calls."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMResponseFormat(StrEnum):
    """Expected response format for an LLM generation call."""

    TEXT = "text"
    JSON = "json"


class LLMProviderRunContext(BaseModel):
    """Execution context passed to LLM provider calls."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID | None = None
    workflow_run_id: UUID | None = None
    agent_name: str | None = None
    correlation_id: str | None = None


class LLMMessage(BaseModel):
    """Provider-neutral chat message."""

    model_config = ConfigDict(extra="forbid")

    role: LLMMessageRole
    content: str = Field(min_length=1)


class LLMGenerationRequest(BaseModel):
    """Provider-neutral LLM generation request."""

    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage] = Field(min_length=1)
    prompt_id: str | None = None
    prompt_version: str | None = None
    response_format: LLMResponseFormat = LLMResponseFormat.JSON
    response_schema_name: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    metadata: dict[str, object] = Field(default_factory=dict)


class LLMGenerationResult(BaseModel):
    """Normalized LLM generation output."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    output_text: str
    structured_output: dict[str, object] | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol every LLM provider adapter should implement."""

    @property
    def name(self) -> str:
        """Return the stable provider name."""

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        """Generate text or structured output from model messages."""
