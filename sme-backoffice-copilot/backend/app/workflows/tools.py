"""Tool interface conventions for workflow agents."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ToolRunStatus(StrEnum):
    """Normalized tool execution outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolDefinitionSpec(BaseModel):
    """Versioned runtime description of a tool."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str | None = None
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    is_deterministic: bool = False


class ToolExecutionContext(BaseModel):
    """Execution context supplied when an agent calls a tool."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    agent_name: str = Field(min_length=1)
    workflow_run_id: UUID | None = None
    correlation_id: str | None = None
    attempt: int = Field(default=1, ge=1)


class ToolCall(BaseModel):
    """Standard tool call envelope."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID = Field(default_factory=uuid4)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = None


class ToolResult(BaseModel):
    """Standard result returned by every workflow tool."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    tool_name: str = Field(min_length=1)
    status: ToolRunStatus
    result: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@runtime_checkable
class WorkflowTool(Protocol):
    """Protocol every agent tool implementation should satisfy."""

    @property
    def definition(self) -> ToolDefinitionSpec:
        """Return the versioned tool definition."""

    async def execute(
        self,
        *,
        call: ToolCall,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute a tool call for one agent step."""
