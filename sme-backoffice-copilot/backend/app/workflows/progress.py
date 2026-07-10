"""Shared workflow progress mapping for status APIs and local runtimes."""

from __future__ import annotations

from dataclasses import dataclass

from app.workflows.contracts import WorkflowStage, WorkflowState, WorkflowStateStatus


@dataclass(frozen=True, slots=True)
class WorkflowProgressSnapshot:
    """A client-safe snapshot of an active or terminal workflow."""

    status: str
    stage: str
    phase: str
    label: str
    percent: int
    current_agent: str | None
    completed_agents: list[str]
    is_terminal: bool


_STAGE_PROGRESS: dict[WorkflowStage, tuple[str, str, int]] = {
    WorkflowStage.INGESTED: ("queued", "Waiting for a worker", 0),
    WorkflowStage.DOCUMENT_INTAKE: ("intake", "Preparing document", 8),
    WorkflowStage.LAYOUT_ANALYSIS: ("ocr", "Reading document with OCR", 25),
    WorkflowStage.PRIVACY_POLICY_GATE: ("privacy", "Applying data policy", 32),
    WorkflowStage.METADATA_EXTRACTION: ("extraction", "Extracting invoice fields", 44),
    WorkflowStage.TABLE_EXTRACTION: ("extraction", "Extracting line items", 54),
    WorkflowStage.TOTALS_EXTRACTION: ("extraction", "Verifying invoice totals", 64),
    WorkflowStage.INVOICE_ASSEMBLY: ("extraction", "Assembling invoice proposal", 70),
    WorkflowStage.QA_VALIDATION: ("qa", "Validating extracted data", 78),
    WorkflowStage.CLASSIFICATION: (
        "classification",
        "Classifying accounting category",
        85,
    ),
    WorkflowStage.RECONCILIATION: (
        "reconciliation",
        "Checking bank transaction matches",
        92,
    ),
    WorkflowStage.REVIEW_COORDINATION: ("review", "Preparing human review", 96),
    WorkflowStage.INSIGHT_GENERATION: ("insights", "Preparing business signals", 99),
    WorkflowStage.COMPLETED: ("completed", "Workflow completed", 100),
    WorkflowStage.FAILED: ("failed", "Workflow failed", 100),
}

_AGENT_STAGE: dict[str, WorkflowStage] = {
    "document_intake": WorkflowStage.DOCUMENT_INTAKE,
    "document_layout_analyzer": WorkflowStage.LAYOUT_ANALYSIS,
    "privacy_policy_gate": WorkflowStage.PRIVACY_POLICY_GATE,
    "metadata_extractor": WorkflowStage.METADATA_EXTRACTION,
    "table_extractor": WorkflowStage.TABLE_EXTRACTION,
    "totals_extractor": WorkflowStage.TOTALS_EXTRACTION,
    "invoice_assembly": WorkflowStage.INVOICE_ASSEMBLY,
    "qa_validator": WorkflowStage.QA_VALIDATION,
    "classification_agent": WorkflowStage.CLASSIFICATION,
    "reconciliation_agent": WorkflowStage.RECONCILIATION,
    "review_coordinator": WorkflowStage.REVIEW_COORDINATION,
    "business_insight_agent": WorkflowStage.INSIGHT_GENERATION,
}


def workflow_stage_for_agent(agent_name: str) -> WorkflowStage | None:
    """Return the user-visible stage associated with an agent definition."""

    return _AGENT_STAGE.get(agent_name)


def build_workflow_progress(state: WorkflowState) -> WorkflowProgressSnapshot:
    """Translate workflow state into stable progress information for clients."""

    status = state.status
    if status is WorkflowStateStatus.QUEUED:
        return _snapshot(
            state=state,
            status=status,
            phase="queued",
            label="Queued for a worker",
            percent=0,
        )
    if status is WorkflowStateStatus.CANCELLED:
        return _snapshot(
            state=state,
            status=status,
            phase="cancelled",
            label="Workflow cancelled before processing",
            percent=0,
        )
    if status is WorkflowStateStatus.REVIEW_REQUIRED:
        return _snapshot(
            state=state,
            status=status,
            phase="review",
            label="Awaiting human review",
            percent=100,
        )
    if status is WorkflowStateStatus.COMPLETED:
        return _snapshot(
            state=state,
            status=status,
            phase="completed",
            label="Workflow completed",
            percent=100,
        )
    if status in {
        WorkflowStateStatus.FAILED,
        WorkflowStateStatus.LOST,
        WorkflowStateStatus.DEAD_LETTERED,
    }:
        return _snapshot(
            state=state,
            status=status,
            phase="failed",
            label="Workflow needs attention",
            percent=100,
        )

    phase, label, percent = _STAGE_PROGRESS.get(
        state.stage,
        ("processing", "Processing document", 5),
    )
    return _snapshot(
        state=state,
        status=status,
        phase=phase,
        label=label,
        percent=percent,
    )


def _snapshot(
    *,
    state: WorkflowState,
    status: WorkflowStateStatus,
    phase: str,
    label: str,
    percent: int,
) -> WorkflowProgressSnapshot:
    return WorkflowProgressSnapshot(
        status=status.value,
        stage=state.stage.value,
        phase=phase,
        label=label,
        percent=percent,
        current_agent=state.current_agent,
        completed_agents=list(state.completed_agents),
        is_terminal=status
        in {
            WorkflowStateStatus.COMPLETED,
            WorkflowStateStatus.REVIEW_REQUIRED,
            WorkflowStateStatus.FAILED,
            WorkflowStateStatus.CANCELLED,
            WorkflowStateStatus.LOST,
            WorkflowStateStatus.DEAD_LETTERED,
        },
    )
