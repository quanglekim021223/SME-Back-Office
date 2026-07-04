from app.models.workflow import WorkflowRunStatus
from app.providers.errors import ProviderDependencyError
from app.providers.ocr import OCRInput, OCRProviderRunContext, OCRResult
from app.workflows import (
    BUSINESS_INSIGHTS_KEY,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    QA_VALIDATION_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    WorkflowStage,
    WorkflowStateStatus,
)
from app.workflows.replay import (
    ReplayScenario,
    WorkflowReplayRunner,
    create_replay_state,
    replay_result_to_summary,
)


class FailingOCRProvider:
    @property
    def name(self) -> str:
        return "failing_ocr"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        del input_data, context
        raise ProviderDependencyError("OCR dependency is not installed.")


async def test_workflow_replay_successful_path_completes_workflow() -> None:
    state = create_replay_state()
    runner = WorkflowReplayRunner()

    result = await runner.run(state=state, scenario=ReplayScenario.HAPPY_PATH)

    assert result.workflow_run.status == WorkflowRunStatus.COMPLETED.value
    assert result.state.status == WorkflowStateStatus.COMPLETED
    assert result.state.stage == WorkflowStage.COMPLETED
    assert result.state.current_agent == "business_insight_agent"
    assert BUSINESS_INSIGHTS_KEY in result.state.scratchpad
    assert len(result.step_executions) == 12
    assert len(result.handoffs) == 13
    assert result.retry_decisions == []
    assert {
        "document_intake",
        "privacy_policy_gate",
        "document_layout_analyzer",
        "metadata_extractor",
        "table_extractor",
        "totals_extractor",
        "invoice_assembly",
        "qa_validator",
        "classification_agent",
        "reconciliation_agent",
        "review_coordinator",
        "business_insight_agent",
    }.issubset(set(result.state.completed_agents))

    summary = replay_result_to_summary(result)
    assert summary["status"] == WorkflowStateStatus.COMPLETED.value
    assert summary["step_count"] == 12


async def test_workflow_replay_failed_validation_routes_self_correction() -> None:
    state = create_replay_state()
    runner = WorkflowReplayRunner()

    result = await runner.run(
        state=state,
        scenario=ReplayScenario.FAILED_VALIDATION,
    )

    assert result.workflow_run.status == WorkflowRunStatus.RUNNING.value
    assert result.state.status == WorkflowStateStatus.RUNNING
    assert result.state.stage == WorkflowStage.TOTALS_EXTRACTION
    assert result.state.current_agent == TOTALS_EXTRACTOR_AGENT
    assert result.state.retry_counts == {TOTALS_EXTRACTOR_AGENT: 1}
    assert len(result.retry_decisions) == 1
    assert result.retry_decisions[0].retry_allowed is True

    retrying_steps = [
        step
        for step in result.step_executions
        if step.agent_name == QA_VALIDATION_AGENT and step.status == "retrying"
    ]
    correction_handoffs = [
        handoff
        for handoff in result.handoffs
        if handoff.source_agent == QA_VALIDATION_AGENT
        and handoff.target_agent == TOTALS_EXTRACTOR_AGENT
        and handoff.handoff_type == "correction"
    ]
    assert len(retrying_steps) == 1
    assert len(correction_handoffs) == 1
    assert correction_handoffs[0].validation_status == "error"


async def test_workflow_replay_retry_exhaustion_dead_letters_workflow() -> None:
    state = create_replay_state(max_retries=3)
    runner = WorkflowReplayRunner()

    result = await runner.run(
        state=state,
        scenario=ReplayScenario.RETRY_EXHAUSTION,
    )

    assert result.workflow_run.status == WorkflowRunStatus.DEAD_LETTERED.value
    assert result.workflow_run.error_code == "RETRY_EXHAUSTED"
    assert result.state.status == WorkflowStateStatus.DEAD_LETTERED
    assert result.state.stage == WorkflowStage.FAILED
    assert result.state.retry_counts == {TOTALS_EXTRACTOR_AGENT: 4}
    assert len(result.retry_decisions) == 4
    assert [decision.retry_allowed for decision in result.retry_decisions] == [
        True,
        True,
        True,
        False,
    ]

    qa_retry_steps = [
        step
        for step in result.step_executions
        if step.agent_name == QA_VALIDATION_AGENT and step.status == "retrying"
    ]
    assert len(qa_retry_steps) == 4


async def test_workflow_replay_stops_when_ocr_provider_fails() -> None:
    from app.providers import ProviderRuntime, build_default_provider_routing_config

    state = create_replay_state()
    runner = WorkflowReplayRunner(
        provider_runtime=ProviderRuntime(build_default_provider_routing_config()),
        ocr_provider=FailingOCRProvider(),
    )

    result = await runner.run(state=state, scenario=ReplayScenario.HAPPY_PATH)

    assert result.workflow_run.status == WorkflowRunStatus.FAILED.value
    assert result.workflow_run.error_code == "ERR_OCR_PROVIDER_FAILED"
    assert result.state.status == WorkflowStateStatus.FAILED
    assert result.state.stage == WorkflowStage.FAILED
    assert result.step_executions[-1].agent_name == DOCUMENT_LAYOUT_ANALYZER_AGENT
    assert result.step_executions[-1].status == "failed"
