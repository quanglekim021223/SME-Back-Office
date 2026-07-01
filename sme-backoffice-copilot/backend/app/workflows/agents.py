"""Base agent interfaces for controlled workflow orchestration."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.contracts import (
    AgentHandoffEnvelope,
    ConfidenceLevel,
    QAErrorSignal,
    WorkflowState,
)


class AgentRunStatus(StrEnum):
    """Normalized agent execution outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    RETRY_REQUESTED = "retry_requested"
    SKIPPED = "skipped"


class AgentDefinitionSpec(BaseModel):
    """Versioned runtime description of an agent."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str | None = None
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)


class AgentExecutionContext(BaseModel):
    """Execution context passed to every agent invocation."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    document_id: UUID
    workflow_run_id: UUID | None = None
    correlation_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    max_retries: int = Field(default=3, ge=0)


class AgentRunResult(BaseModel):
    """Standard result returned by every workflow agent."""

    model_config = ConfigDict(extra="forbid")

    status: AgentRunStatus
    output: dict[str, object] = Field(default_factory=dict)
    handoffs: list[AgentHandoffEnvelope] = Field(default_factory=list)
    qa_error_signals: list[QAErrorSignal] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    metrics: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@runtime_checkable
class BaseAgent(Protocol):
    """Protocol every workflow agent implementation should satisfy."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned agent definition."""

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Run the agent for one workflow step."""
