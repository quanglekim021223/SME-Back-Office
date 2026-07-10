from uuid import uuid4

from app.workflows.contracts import WorkflowStage, WorkflowState, WorkflowStateStatus
from app.workflows.progress import build_workflow_progress, workflow_stage_for_agent


def test_workflow_progress_maps_ocr_and_extraction_stages() -> None:
    state = WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        status=WorkflowStateStatus.RUNNING,
        stage=WorkflowStage.LAYOUT_ANALYSIS,
        current_agent="document_layout_analyzer",
    )

    progress = build_workflow_progress(state)

    assert progress.phase == "ocr"
    assert progress.percent == 25
    assert progress.current_agent == "document_layout_analyzer"
    assert progress.is_terminal is False
    assert (
        workflow_stage_for_agent("classification_agent") is WorkflowStage.CLASSIFICATION
    )


def test_workflow_progress_marks_review_required_as_terminal() -> None:
    state = WorkflowState(
        tenant_id=uuid4(),
        document_id=uuid4(),
        document_type="invoice",
        status=WorkflowStateStatus.REVIEW_REQUIRED,
        stage=WorkflowStage.REVIEW_COORDINATION,
    )

    progress = build_workflow_progress(state)

    assert progress.phase == "review"
    assert progress.percent == 100
    assert progress.is_terminal is True
