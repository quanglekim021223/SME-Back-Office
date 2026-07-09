"""Business downstream agent skeletons after invoice QA validation."""

from __future__ import annotations

import logging
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.db import async_session_factory
from app.models.banking import Transaction, TransactionDirection
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
    collect_invoice_groups,
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
    candidate_score: int | None = None


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

    # Check reconciliation result
    recon_payload = state.scratchpad.get(RECONCILIATION_RESULT_KEY)
    if recon_payload is not None:
        try:
            recon = ReconciliationDraft.model_validate(recon_payload)
            if recon.requires_review and recon.review_reason:
                reasons.append(recon.review_reason)
        except Exception:
            pass

    return reasons


class ClassificationAgent:
    """Agent that proposes accounting classification using rules."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned classification agent definition."""

        return AgentDefinitionSpec(
            name=CLASSIFICATION_AGENT,
            version="0.1.0",
            description="Creates category and direction proposals using rules.",
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
        """Create classification proposal and route to matching."""

        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=CLASSIFICATION_AGENT,
        )
        if context_error is not None:
            return context_error

        # Collect extraction groups from scratchpad
        groups = collect_invoice_groups(state)

        # Run rules first, then LLM fallback for low/unknown classifications.
        from app.classification.hybrid import classify_with_llm_fallback
        from app.classification.rules import build_invoice_classification_input

        result = await classify_with_llm_fallback(
            build_invoice_classification_input(groups),
            tenant_id=context.tenant_id,
            document_id=context.document_id,
            workflow_run_id=context.workflow_run_id,
            correlation_id=context.correlation_id,
            provider_runtime=context.provider_runtime,
            llm_provider=context.llm_provider,
            privacy_context=context.provider_privacy_context,
        )

        draft = ClassificationDraft(
            classification_status=BusinessDownstreamStatus.READY,
            proposed_category_code=result.category_code,
            proposed_direction=result.proposed_direction,
            rationale=result.rationale,
            evidence_refs=handoff.evidence_refs if handoff is not None else [],
            confidence=result.confidence,
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
                    confidence=result.confidence,
                )
            ],
            confidence=result.confidence,
        )


class ReconciliationAgent:
    """Agent that prepares invoice-to-transaction matching by querying database."""

    @property
    def definition(self) -> AgentDefinitionSpec:
        """Return the versioned reconciliation agent definition."""

        return AgentDefinitionSpec(
            name=RECONCILIATION_AGENT,
            version="0.1.0",
            description=(
                "Matches invoices against bank transactions using deterministic rules."
            ),
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
        """Create reconciliation result by querying DB and scoring candidates."""

        del handoff
        context_error = validate_agent_context(
            state=state,
            context=context,
            agent_name=RECONCILIATION_AGENT,
        )
        if context_error is not None:
            return context_error

        # Collect invoice groups and build match input
        from app.reconciliation.deterministic import (
            ReconciliationTransactionInput,
            build_invoice_match_input,
            generate_reconciliation_candidates,
        )
        groups = collect_invoice_groups(state)
        invoice_input = build_invoice_match_input(groups)

        db_transactions: list[Transaction] = []
        # Query candidate bank transactions dynamically for the tenant
        try:
            async with async_session_factory() as session:
                if invoice_input.total_amount is not None:
                    # Query candidate transactions with similar amounts (+/- 10%)
                    min_amount = invoice_input.total_amount * Decimal("0.9")
                    max_amount = invoice_input.total_amount * Decimal("1.1")
                    stmt = (
                        select(Transaction)
                        .where(
                            Transaction.tenant_id == context.tenant_id,
                            Transaction.amount >= min_amount,
                            Transaction.amount <= max_amount,
                        )
                        .order_by(Transaction.posted_at.desc())
                    )
                    result = await session.execute(stmt)
                    db_transactions = list(result.scalars().all())

                if not db_transactions:
                    # Fallback: query recent transactions for the tenant
                    stmt = (
                        select(Transaction)
                        .where(Transaction.tenant_id == context.tenant_id)
                        .order_by(Transaction.posted_at.desc())
                        .limit(100)
                    )
                    result = await session.execute(stmt)
                    db_transactions = list(result.scalars().all())
        except Exception as e:
            logger = logging.getLogger("app.workflows.downstream_agents")
            logger.warning("Failed to query transactions from database: %s", e)

        if not db_transactions:
            # Local replay can synthesize a match to complete the happy path.
            from app.core.config import get_settings
            settings = get_settings()
            if settings.app_env in {"test", "local"}:
                import uuid
                from datetime import date
                invoice_amount = invoice_input.total_amount or Decimal("100.00")
                issue_date = invoice_input.issue_date or date.today()
                synth_tx = Transaction(
                    id=uuid.uuid4(),
                    tenant_id=context.tenant_id,
                    bank_account_id=uuid.uuid4(),
                    status="posted",
                    direction=TransactionDirection.OUTFLOW.value,
                    posted_at=issue_date,
                    value_at=issue_date,
                    raw_description=(
                        f"Payment for {invoice_input.invoice_number or 'INV-999'}"
                    ),
                    normalized_description="Payment",
                    counterparty_name=(
                        invoice_input.counterparty_names[0]
                        if invoice_input.counterparty_names
                        else "Supplier"
                    ),
                    reference=invoice_input.invoice_number,
                    amount=-abs(invoice_amount),
                    currency=invoice_input.currency or "USD",
                    content_hash="synthetic-hash",
                    metadata_={},
                )
                db_transactions = [synth_tx]

        # Map DB transactions to match inputs
        tx_inputs: list[ReconciliationTransactionInput] = []
        for tx in db_transactions:
            try:
                direction = TransactionDirection(tx.direction)
            except (ValueError, TypeError):
                direction = TransactionDirection.UNKNOWN

            tx_inputs.append(
                ReconciliationTransactionInput(
                    transaction_id=str(tx.id),
                    posted_at=tx.posted_at,
                    value_at=tx.value_at,
                    amount=tx.amount,
                    currency=tx.currency,
                    direction=direction,
                    reference=tx.reference,
                    description=tx.raw_description or tx.normalized_description,
                    counterparty_name=tx.counterparty_name,
                    content_hash=tx.content_hash,
                    metadata=tx.metadata_ or {},
                )
            )

        # Generate candidates using deterministic match scorer
        candidates = generate_reconciliation_candidates(
            invoice=invoice_input,
            transactions=tx_inputs,
            min_score=1,
        )

        matched_refs = [c.transaction_id for c in candidates]
        candidate_count = len(candidates)

        # Heuristics for review status
        if candidate_count == 0:
            reconciliation_status = BusinessDownstreamStatus.REVIEW_REQUIRED
            requires_review = True
            review_reason = "no_matching_transaction"
            confidence = ConfidenceLevel.UNKNOWN
        elif candidate_count > 1:
            reconciliation_status = BusinessDownstreamStatus.REVIEW_REQUIRED
            requires_review = True
            review_reason = "ambiguous_match"
            confidence = candidates[0].confidence
        else:
            candidate = candidates[0]
            confidence = candidate.confidence
            if candidate.score < 85:
                reconciliation_status = BusinessDownstreamStatus.REVIEW_REQUIRED
                requires_review = True
                review_reason = "low_confidence_match"
            else:
                reconciliation_status = BusinessDownstreamStatus.READY
                requires_review = False
                review_reason = None

        draft = ReconciliationDraft(
            reconciliation_status=reconciliation_status,
            matched_transaction_refs=matched_refs,
            candidate_count=candidate_count,
            requires_review=requires_review,
            review_reason=review_reason,
            confidence=confidence,
            candidate_score=candidates[0].score if candidate_count > 0 else None,
        )
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
                    confidence=confidence,
                )
            ],
            confidence=confidence,
            metrics={"candidate_count": candidate_count},
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
                else BusinessDownstreamStatus.READY
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
