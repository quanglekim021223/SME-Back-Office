"""Business downstream agent skeletons after invoice QA validation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.workflows.agents import (
    AgentDefinitionSpec,
    AgentExecutionContext,
    AgentRunResult,
    AgentRunStatus,
)
from app.workflows.contracts import (
    AgentHandoffEnvelope,
    ConfidenceLevel,
    QAErrorSeverity,
    WorkflowStage,
    WorkflowState,
)
from app.workflows.document_preparation import (
    build_control_handoff,
    validate_agent_context,
)
from app.workflows.invoice_extraction import (
    ASSEMBLED_INVOICE_DRAFT_KEY,
    CLASSIFICATION_AGENT,
    build_data_handoff,
    model_to_payload,
)

RECONCILIATION_AGENT = "reconciliation_agent"
REVIEW_COORDINATOR_AGENT = "review_coordinator"
BUSINESS_INSIGHT_AGENT = "business_insight_agent"

CLASSIFICATION_PROPOSAL_KEY = "classification_proposal"
RECONCILIATION_RESULT_KEY = "reconciliation_result"
REVIEW_COORDINATION_RESULT_KEY = "review_coordination_result"
BUSINESS_INSIGHTS_KEY = "business_insights"


class BusinessDownstreamStatus(StrEnum):
    """Lifecycle status for downstream business agent placeholder outputs."""

    PLACEHOLDER = "placeholder"
    READY = "ready"
    REVIEW_REQUIRED = "review_required"
    SKIPPED = "skipped"


class ClassificationDraft(BaseModel):
    """Placeholder classification proposal produced after QA validation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "classification-draft.v1"
    classification_status: BusinessDownstreamStatus = (
        BusinessDownstreamStatus.PLACEHOLDER
    )
    subject_type: str = "invoice"
    subject_ref: str = ASSEMBLED_INVOICE_DRAFT_KEY
    proposed_category_code: str | None = None
    proposed_direction: str | None = None
    rationale: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class ReconciliationDraft(BaseModel):
    """Placeholder reconciliation result produced before matching logic exists."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "reconciliation-draft.v1"
    reconciliation_status: BusinessDownstreamStatus = (
        BusinessDownstreamStatus.PLACEHOLDER
    )
    invoice_ref: str = ASSEMBLED_INVOICE_DRAFT_KEY
    classification_ref: str = CLASSIFICATION_PROPOSAL_KEY
    matched_transaction_refs: list[str] = Field(default_factory=list)
    candidate_count: int = Field(default=0, ge=0)
    requires_review: bool = False
    review_reason: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class ReviewCoordinationDraft(BaseModel):
    """Placeholder review coordination decision."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "review-coordination-draft.v1"
    review_status: BusinessDownstreamStatus = BusinessDownstreamStatus.PLACEHOLDER
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    review_task_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class BusinessInsightDraft(BaseModel):
    """Placeholder insight package produced at the end of the workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "business-insight-draft.v1"
    insight_status: BusinessDownstreamStatus = BusinessDownstreamStatus.PLACEHOLDER
    source_refs: list[str] = Field(default_factory=list)
    insight_count: int = Field(default=0, ge=0)
    insights: list[dict[str, object]] = Field(default_factory=list)
    summary: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN


def blocking_review_reasons(state: WorkflowState) -> list[str]:
    """Return high-level reasons that should stop automated downstream handling."""

    reasons: list[str] = []
    for signal in state.qa_error_signals:
        if signal.severity in {QAErrorSeverity.ERROR, QAErrorSeverity.BLOCKING}:
            reasons.append(signal.code)
    return reasons


class ClassificationAgent:
    """Skeleton agent that proposes accounting classification placeholders."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned classification agent definition."""

        return AgentDefinitionSpec(
            name=CLASSIFICATION_AGENT,
            version="0.1.0",
            description="Creates placeholder category and direction proposals.",
            input_schema_ref="assembled-invoice-draft.v1",
            output_schema_ref="classification-draft.v1",
            allowed_tools=["rule_based_category_classifier"],
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Create a placeholder classification proposal and route to matching."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=CLASSIFICATION_AGENT,
        )
        if context_error is not None:
            return context_error

        draft = ClassificationDraft(
            evidence_refs=handoff.evidence_refs if handoff is not None else [],
            rationale="Placeholder classification; no classifier provider configured.",
        )
        draft_payload = model_to_payload(draft)
        state.scratchpad[CLASSIFICATION_PROPOSAL_KEY] = draft_payload
        output: dict[str, object] = {
            "classification": draft_payload,
            "classification_ref": CLASSIFICATION_PROPOSAL_KEY,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=CLASSIFICATION_AGENT,
                    target_agent=RECONCILIATION_AGENT,
                    stage=WorkflowStage.RECONCILIATION,
                    payload=output,
                    evidence_refs=draft.evidence_refs,
                    confidence=ConfidenceLevel.UNKNOWN,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
        )


class ReconciliationAgent:
    """Skeleton agent that prepares invoice-to-transaction matching placeholders."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned reconciliation agent definition."""

        return AgentDefinitionSpec(
            name=RECONCILIATION_AGENT,
            version="0.1.0",
            description="Creates placeholder reconciliation candidates.",
            input_schema_ref="classification-draft.v1",
            output_schema_ref="reconciliation-draft.v1",
            allowed_tools=["deterministic_match_scorer"],
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Create a placeholder reconciliation result and route to review."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=RECONCILIATION_AGENT,
        )
        if context_error is not None:
            return context_error

        draft = ReconciliationDraft()
        draft_payload = model_to_payload(draft)
        state.scratchpad[RECONCILIATION_RESULT_KEY] = draft_payload
        output: dict[str, object] = {
            "reconciliation": draft_payload,
            "reconciliation_ref": RECONCILIATION_RESULT_KEY,
        }
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_data_handoff(
                    state=state,
                    source_agent=RECONCILIATION_AGENT,
                    target_agent=REVIEW_COORDINATOR_AGENT,
                    stage=WorkflowStage.REVIEW_COORDINATION,
                    payload=output,
                    confidence=ConfidenceLevel.UNKNOWN,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
            metrics={"candidate_count": draft.candidate_count},
        )


class ReviewCoordinatorAgent:
    """Skeleton agent that decides whether human review is required."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned review coordinator definition."""

        return AgentDefinitionSpec(
            name=REVIEW_COORDINATOR_AGENT,
            version="0.1.0",
            description="Creates placeholder review decisions before ReviewTask logic.",
            input_schema_ref="reconciliation-draft.v1",
            output_schema_ref="review-coordination-draft.v1",
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Route clean records to insights or stop for human review."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=REVIEW_COORDINATOR_AGENT,
        )
        if context_error is not None:
            return context_error

        review_reasons = blocking_review_reasons(state)
        review_required = bool(review_reasons)
        draft = ReviewCoordinationDraft(
            review_status=(
                BusinessDownstreamStatus.REVIEW_REQUIRED
                if review_required
                else BusinessDownstreamStatus.PLACEHOLDER
            ),
            review_required=review_required,
            review_reasons=review_reasons,
            confidence=ConfidenceLevel.HIGH
            if review_required
            else ConfidenceLevel.UNKNOWN,
        )
        draft_payload = model_to_payload(draft)
        state.scratchpad[REVIEW_COORDINATION_RESULT_KEY] = draft_payload
        output: dict[str, object] = {
            "review_coordination": draft_payload,
            "review_coordination_ref": REVIEW_COORDINATION_RESULT_KEY,
        }
        if review_required:
            return AgentRunResult(
                status=AgentRunStatus.REVIEW_REQUIRED,
                output=output,
                confidence=ConfidenceLevel.HIGH,
                metrics={"review_reason_count": len(review_reasons)},
            )

        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output=output,
            handoffs=[
                build_control_handoff(
                    state=state,
                    source_agent=REVIEW_COORDINATOR_AGENT,
                    target_agent=BUSINESS_INSIGHT_AGENT,
                    stage=WorkflowStage.INSIGHT_GENERATION,
                    payload=output,
                    confidence=ConfidenceLevel.UNKNOWN,
                )
            ],
            confidence=ConfidenceLevel.UNKNOWN,
        )


class BusinessInsightAgent:
    """Skeleton agent that produces a placeholder business insight package."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned business insight agent definition."""

        return AgentDefinitionSpec(
            name=BUSINESS_INSIGHT_AGENT,
            version="0.1.0",
            description="Creates placeholder insight output for dashboards.",
            input_schema_ref="review-coordination-draft.v1",
            output_schema_ref="business-insight-draft.v1",
            allowed_tools=["cashflow_summary_builder"],
        )

    async def run(
        self,
        *,
        state: WorkflowState,
        context: AgentExecutionContext,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Create an empty insight package until analytics logic exists."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=BUSINESS_INSIGHT_AGENT,
        )
        if context_error is not None:
            return context_error

        draft = BusinessInsightDraft(
            source_refs=[
                ASSEMBLED_INVOICE_DRAFT_KEY,
                CLASSIFICATION_PROPOSAL_KEY,
                RECONCILIATION_RESULT_KEY,
                REVIEW_COORDINATION_RESULT_KEY,
            ],
            summary=(
                "Placeholder insight package; analytics providers are not configured."
            ),
        )
        draft_payload = model_to_payload(draft)
        state.scratchpad[BUSINESS_INSIGHTS_KEY] = draft_payload
        return AgentRunResult(
            status=AgentRunStatus.SUCCEEDED,
            output={
                "business_insights": draft_payload,
                "business_insights_ref": BUSINESS_INSIGHTS_KEY,
            },
            confidence=ConfidenceLevel.UNKNOWN,
            metrics={"insight_count": draft.insight_count},
        )
