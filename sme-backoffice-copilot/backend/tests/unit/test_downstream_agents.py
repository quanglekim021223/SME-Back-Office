from typing import Any, cast
from uuid import uuid4

import pytest

from app.workflows import (
    ASSEMBLED_INVOICE_DRAFT_KEY,
    BUSINESS_INSIGHT_AGENT,
    BUSINESS_INSIGHTS_KEY,
    CLASSIFICATION_AGENT,
    CLASSIFICATION_PROPOSAL_KEY,
    RECONCILIATION_AGENT,
    RECONCILIATION_RESULT_KEY,
    REVIEW_COORDINATION_RESULT_KEY,
    REVIEW_COORDINATOR_AGENT,
    AgentExecutionContext,
    AgentHandoffEnvelope,
    AgentRunStatus,
    BaseAgent,
    BusinessDownstreamStatus,
    BusinessInsightAgent,
    ClassificationAgent,
    ConfidenceLevel,
    HandoffType,
    QAErrorSeverity,
    QAErrorSignal,
    ReconciliationAgent,
    ReviewCoordinatorAgent,
    WorkflowStage,
    WorkflowState,
)


def create_state() -> WorkflowState:
    return WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        workflow_run_id=uuid4(),
        scratchpad={
            ASSEMBLED_INVOICE_DRAFT_KEY: {
                "schema_version": "assembled-invoice-draft.v1",
            },
            "invoice_metadata_group": {
                "schema_version": "invoice-metadata-group.v1",
                "extraction_status": "extracted",
                "invoice_number": "INV-12345",
                "supplier_name": "Google Cloud",
                "customer_name": "ACME Corp",
                "issue_date": "2026-07-01",
                "due_date": "2026-07-31",
                "currency": "USD"
            },
            "invoice_totals_group": {
                "schema_version": "invoice-totals-group.v1",
                "extraction_status": "extracted",
                "total_amount": "1250.00",
                "currency": "USD"
            }
        },
    )


def create_context(state: WorkflowState) -> AgentExecutionContext:
    return AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
    )


def create_handoff(
    *,
    state: WorkflowState,
    source_agent: str,
    target_agent: str,
    stage: WorkflowStage,
) -> AgentHandoffEnvelope:
    return AgentHandoffEnvelope(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
        source_agent=source_agent,
        target_agent=target_agent,
        handoff_type=HandoffType.DATA,
        stage=stage,
        payload={"source_ref": ASSEMBLED_INVOICE_DRAFT_KEY},
        evidence_refs=["page:1"],
        confidence=ConfidenceLevel.UNKNOWN,
    )


@pytest.mark.asyncio
async def test_downstream_agents_route_clean_invoice_to_insights() -> None:
    from datetime import date
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.models.banking import Transaction

    state = create_state()
    context = create_context(state)

    classification_agent = ClassificationAgent()
    reconciliation_agent = ReconciliationAgent()
    review_agent = ReviewCoordinatorAgent()
    insight_agent = BusinessInsightAgent()

    assert isinstance(classification_agent, BaseAgent)
    assert classification_agent.definition.name == CLASSIFICATION_AGENT

    classification_result = await classification_agent.run(
        state=state,
        context=context,
        handoff=create_handoff(
            state=state,
            source_agent="qa_validator",
            target_agent=CLASSIFICATION_AGENT,
            stage=WorkflowStage.CLASSIFICATION,
        ),
    )

    assert classification_result.status == AgentRunStatus.SUCCEEDED
    assert CLASSIFICATION_PROPOSAL_KEY in state.scratchpad
    assert classification_result.handoffs[0].source_agent == CLASSIFICATION_AGENT
    assert classification_result.handoffs[0].target_agent == RECONCILIATION_AGENT
    assert classification_result.handoffs[0].stage == WorkflowStage.RECONCILIATION

    # Mock the database transaction match
    mock_tx = MagicMock(spec=Transaction)
    mock_tx.id = uuid4()
    mock_tx.direction = "outflow"
    mock_tx.posted_at = date(2026, 7, 10)
    mock_tx.value_at = date(2026, 7, 10)
    mock_tx.amount = Decimal("-1250.00")
    mock_tx.currency = "USD"
    mock_tx.reference = "INV-12345"
    mock_tx.raw_description = "Google Cloud Service INV-12345"
    mock_tx.normalized_description = "Google Cloud Service"
    mock_tx.counterparty_name = "Google Cloud"
    mock_tx.content_hash = "somehash"
    mock_tx.metadata_ = {}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_tx]
    mock_session.execute.return_value = mock_result

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session

    with patch(
        "app.workflows.downstream_agents.async_session_factory",
        mock_session_factory,
    ):
        reconciliation_result = await reconciliation_agent.run(
            state=state,
            context=context,
            handoff=classification_result.handoffs[0],
        )

    assert reconciliation_result.status == AgentRunStatus.SUCCEEDED
    assert reconciliation_result.metrics == {"candidate_count": 1}
    assert RECONCILIATION_RESULT_KEY in state.scratchpad
    assert reconciliation_result.handoffs[0].source_agent == RECONCILIATION_AGENT
    assert reconciliation_result.handoffs[0].target_agent == REVIEW_COORDINATOR_AGENT
    assert reconciliation_result.handoffs[0].stage == WorkflowStage.REVIEW_COORDINATION

    review_result = await review_agent.run(
        state=state,
        context=context,
        handoff=reconciliation_result.handoffs[0],
    )

    assert review_result.status == AgentRunStatus.SUCCEEDED
    assert REVIEW_COORDINATION_RESULT_KEY in state.scratchpad
    assert review_result.handoffs[0].source_agent == REVIEW_COORDINATOR_AGENT
    assert review_result.handoffs[0].target_agent == BUSINESS_INSIGHT_AGENT
    assert review_result.handoffs[0].stage == WorkflowStage.INSIGHT_GENERATION

    insight_result = await insight_agent.run(
        state=state,
        context=context,
        handoff=review_result.handoffs[0],
    )

    assert insight_result.status == AgentRunStatus.SUCCEEDED
    assert insight_result.handoffs == []
    assert insight_result.metrics == {"insight_count": 0}
    assert BUSINESS_INSIGHTS_KEY in state.scratchpad
    assert insight_result.output["business_insights_ref"] == BUSINESS_INSIGHTS_KEY


@pytest.mark.asyncio
async def test_review_coordinator_stops_when_blocking_qa_errors_exist() -> None:
    state = create_state()
    context = create_context(state)
    state.qa_error_signals.append(
        QAErrorSignal(
            code="ERR_LOGIC_MATH",
            severity=QAErrorSeverity.BLOCKING,
            message="Invoice total still does not match after retries.",
            source_agent="qa_validator",
            retryable=False,
        )
    )

    result = await ReviewCoordinatorAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.REVIEW_REQUIRED
    assert result.handoffs == []
    assert result.output["review_coordination_ref"] == REVIEW_COORDINATION_RESULT_KEY
    review_payload = cast(
        dict[str, Any],
        state.scratchpad[REVIEW_COORDINATION_RESULT_KEY],
    )
    assert review_payload["review_status"] == BusinessDownstreamStatus.REVIEW_REQUIRED
    assert review_payload["review_required"] is True
    assert review_payload["review_reasons"] == ["ERR_LOGIC_MATH"]


@pytest.mark.asyncio
async def test_downstream_agents_fail_on_context_mismatch() -> None:
    state = create_state()
    context = AgentExecutionContext(
        tenant_id=uuid4(),
        document_id=state.document_id,
        workflow_run_id=state.workflow_run_id,
    )

    result = await ClassificationAgent().run(state=state, context=context)

    assert result.status == AgentRunStatus.FAILED
    assert result.error_code == "ERR_WORKFLOW_CONTEXT_MISMATCH"
