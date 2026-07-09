"""Local workflow replay command for testing the skeleton agent flow."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.workflows.agents import (
    AgentExecutionContext,
    AgentRunResult,
    AgentRunStatus,
    BaseAgent,
)
from app.workflows.contracts import (
    AgentHandoffEnvelope,
    HandoffType,
    WorkflowArtifactRef,
    WorkflowStage,
    WorkflowState,
    WorkflowStateStatus,
)
from app.workflows.document_preparation import (
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    METADATA_EXTRACTOR_AGENT,
    PRIVACY_POLICY_GATE_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    DocumentIntakeAgent,
    DocumentLayoutAnalyzerAgent,
    PrivacyPolicyGateAgent,
)
from app.workflows.downstream_agents import (
    BUSINESS_INSIGHT_AGENT,
    BusinessInsightAgent,
    ClassificationAgent,
    ReconciliationAgent,
    ReviewCoordinatorAgent,
)
from app.workflows.invoice_extraction import (
    CLASSIFICATION_AGENT,
    QA_VALIDATION_AGENT,
    InvoiceAssemblyNode,
    MetadataExtractorAgent,
    QAValidationAgent,
    TableExtractorAgent,
    TotalsExtractorAgent,
    create_total_amount_correction_signal,
)
from app.workflows.runtime import (
    RetryDecision,
    WorkflowRuntimePersistence,
    WorkflowRuntimeService,
)

if TYPE_CHECKING:
    from app.providers import LLMProvider, OCRProvider


WORKFLOW_REPLAY_NAME = "document_processing_replay"
WORKFLOW_REPLAY_VERSION = "0.1.0"


class ReplayScenario(StrEnum):
    """Supported local workflow replay scenarios."""

    HAPPY_PATH = "happy_path"
    FAILED_VALIDATION = "failed_validation"
    RETRY_EXHAUSTION = "retry_exhaustion"


@dataclass(slots=True)
class InMemoryWorkflowRuntimePersistence:
    """In-memory persistence adapter used by local workflow replay."""

    workflow_runs: list[WorkflowRun] = field(default_factory=list)
    step_executions: list[AgentStepExecution] = field(default_factory=list)
    handoffs: list[AgentHandoff] = field(default_factory=list)

    def add_workflow_run(self, workflow_run: WorkflowRun) -> WorkflowRun:
        """Store a workflow run in memory."""

        self.workflow_runs.append(workflow_run)
        return workflow_run

    def add_step_execution(
        self,
        step_execution: AgentStepExecution,
    ) -> AgentStepExecution:
        """Store an agent step execution in memory."""

        self.step_executions.append(step_execution)
        return step_execution

    def add_handoff(self, handoff: AgentHandoff) -> AgentHandoff:
        """Store an agent handoff in memory."""

        self.handoffs.append(handoff)
        return handoff


@dataclass(frozen=True, slots=True)
class WorkflowReplayResult:
    """Result returned by a local workflow replay run."""

    scenario: ReplayScenario
    state: WorkflowState
    workflow_run: WorkflowRun
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]
    retry_decisions: list[RetryDecision]


def create_replay_state(
    *,
    tenant_id: UUID | None = None,
    document_id: UUID | None = None,
    max_retries: int = 3,
) -> WorkflowState:
    """Create a replayable workflow state without requiring database records."""

    resolved_tenant_id = tenant_id or uuid4()
    resolved_document_id = document_id or uuid4()
    return WorkflowState(
        tenant_id=resolved_tenant_id,
        document_id=resolved_document_id,
        document_type="invoice",
        max_retries=max_retries,
        artifacts={
            "original": WorkflowArtifactRef(
                artifact_type="original",
                uri=(
                    "local://replay/"
                    f"tenants/{resolved_tenant_id}/documents/{resolved_document_id}"
                ),
                media_type="application/pdf",
                content_hash="replay-placeholder-hash",
            )
        },
        policy_flags={"malware_scan_status": "clean_placeholder"},
    )


class WorkflowReplayRunner:
    """Small local runner that replays the skeleton workflow without frontend/API."""

    persistence: WorkflowRuntimePersistence
    runtime: WorkflowRuntimeService
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]
    provider_runtime: Any | None
    llm_provider: LLMProvider | None
    ocr_provider: OCRProvider | None
    provider_privacy_context: Any | None
    trace_provider: Any | None

    def __init__(
        self,
        persistence: WorkflowRuntimePersistence | None = None,
        provider_runtime: Any | None = None,
        llm_provider: Any | None = None,
        ocr_provider: Any | None = None,
        provider_privacy_context: Any | None = None,
        trace_provider: Any | None = None,
    ) -> None:
        self.persistence = persistence or InMemoryWorkflowRuntimePersistence()
        self.runtime = WorkflowRuntimeService(self.persistence)
        self.step_executions: list[AgentStepExecution] = []
        self.handoffs: list[AgentHandoff] = []

        if provider_runtime is None or llm_provider is None or ocr_provider is None:
            from app.core.config import LLMProviderType, OCRProviderType, Settings
            from app.providers import (
                ProviderRuntime,
                build_default_provider_routing_config,
            )
            from app.providers.factory import (
                build_llm_provider_from_settings,
                build_ocr_provider_from_settings,
            )

            # Use mock settings for deterministic replay
            settings = Settings(
                ocr_provider=OCRProviderType.MOCK,
                llm_provider=LLMProviderType.MOCK,
            )

            self.provider_runtime = provider_runtime or ProviderRuntime(
                build_default_provider_routing_config()
            )
            self.llm_provider = llm_provider or build_llm_provider_from_settings(
                settings
            )
            self.ocr_provider = ocr_provider or build_ocr_provider_from_settings(
                settings
            )
        else:
            self.provider_runtime = provider_runtime
            self.llm_provider = llm_provider
            self.ocr_provider = ocr_provider

        self.provider_privacy_context = provider_privacy_context
        self.trace_provider = trace_provider

    async def run(
        self,
        *,
        state: WorkflowState,
        scenario: ReplayScenario = ReplayScenario.HAPPY_PATH,
        correlation_id: str | None = None,
    ) -> WorkflowReplayResult:
        """Replay the controlled multi-agent workflow for one scenario."""

        self.step_executions = []
        self.handoffs = []
        workflow_run = self.runtime.start_workflow(
            state=state,
            workflow_name=WORKFLOW_REPLAY_NAME,
            workflow_version=WORKFLOW_REPLAY_VERSION,
            correlation_id=correlation_id,
        )
        context = AgentExecutionContext(
            tenant_id=state.tenant_id,
            document_id=state.document_id,
            workflow_run_id=workflow_run.id,
            max_retries=state.max_retries,
            provider_runtime=self.provider_runtime,
            llm_provider=self.llm_provider,
            ocr_provider=self.ocr_provider,
            provider_privacy_context=self.provider_privacy_context,
            trace_provider=self.trace_provider,
        )
        from app.core.config import WorkflowOrchestrationMode, get_settings
        from app.workflows.langgraph_adapter import (
            LangGraphWorkflowAdapter,
            is_langgraph_available,
        )

        settings = get_settings()
        if (
            settings.workflow_orchestration_mode == WorkflowOrchestrationMode.LANGGRAPH
            and is_langgraph_available()
            and scenario == ReplayScenario.HAPPY_PATH
        ):
            # Run using the LangGraph adapter
            adapter = LangGraphWorkflowAdapter(self.runtime)
            graph_result = await adapter.run_invoice_extraction_until_qa(
                state=state,
                workflow_run=workflow_run,
                context=context,
            )

            # Copy graph results into runner's state
            self.step_executions.extend(graph_result.step_executions)
            self.handoffs.extend(graph_result.handoffs)
            retry_decisions = list(graph_result.retry_decisions)

            # Locate QA validation step to determine qa_result
            qa_step = next(
                (
                    step
                    for step in reversed(graph_result.step_executions)
                    if step.agent_name == QA_VALIDATION_AGENT
                ),
                None,
            )
            qa_status = AgentRunStatus.SUCCEEDED
            if qa_step is not None:
                if qa_step.status == "failed":
                    qa_status = AgentRunStatus.FAILED
                elif qa_step.status == "review_required":
                    qa_status = AgentRunStatus.REVIEW_REQUIRED
                elif qa_step.status == "retrying":
                    qa_status = AgentRunStatus.RETRY_REQUESTED

            # Map database handoff models back to AgentHandoffEnvelope pydantic models

            stage_map = {
                "document_intake": WorkflowStage.DOCUMENT_INTAKE,
                "privacy_policy_gate": WorkflowStage.PRIVACY_POLICY_GATE,
                "document_layout_analyzer": WorkflowStage.LAYOUT_ANALYSIS,
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

            handoff_envelopes = []
            for h in graph_result.handoffs:
                handoff_envelopes.append(
                    AgentHandoffEnvelope(
                        handoff_id=h.id,
                        tenant_id=h.tenant_id,
                        document_id=state.document_id,
                        workflow_run_id=h.workflow_run_id,
                        source_agent=h.source_agent,
                        target_agent=h.target_agent,
                        handoff_type=HandoffType(h.handoff_type),
                        stage=stage_map.get(h.target_agent, WorkflowStage.FAILED),
                        payload={},
                        attempt=h.attempt,
                    )
                )

            qa_result = AgentRunResult(
                status=qa_status,
                output={},
                handoffs=handoff_envelopes,
                error_code=qa_step.error_code if qa_step else None,
            )

            if state.status in {
                WorkflowStateStatus.FAILED,
                WorkflowStateStatus.REVIEW_REQUIRED,
                WorkflowStateStatus.DEAD_LETTERED,
            } or is_terminal_agent_result(qa_result):
                return self._build_result(
                    scenario=scenario,
                    state=state,
                    workflow_run=workflow_run,
                    retry_decisions=retry_decisions,
                )

            # Otherwise proceed downstream
            await self._run_successful_downstream(
                workflow_run=workflow_run,
                state=state,
                context=context,
                qa_result=qa_result,
            )
            self.runtime.update_workflow_status(
                workflow_run=workflow_run,
                state=state,
                status=WorkflowStateStatus.COMPLETED,
                stage=WorkflowStage.COMPLETED,
                current_agent=BUSINESS_INSIGHT_AGENT,
            )
            return self._build_result(
                scenario=scenario,
                state=state,
                workflow_run=workflow_run,
                retry_decisions=retry_decisions,
            )

        qa_result = await self._run_until_qa(
            workflow_run=workflow_run,
            state=state,
            context=context,
            inject_validation_error=scenario
            in {
                ReplayScenario.FAILED_VALIDATION,
                ReplayScenario.RETRY_EXHAUSTION,
            },
        )
        retry_decisions: list[RetryDecision] = []
        if is_terminal_agent_result(qa_result):
            return self._build_result(
                scenario=scenario,
                state=state,
                workflow_run=workflow_run,
                retry_decisions=retry_decisions,
            )

        if scenario == ReplayScenario.FAILED_VALIDATION:
            retry_decisions.extend(
                self._request_retries_for_correction_handoffs(
                    workflow_run=workflow_run,
                    state=state,
                    result=qa_result,
                )
            )
            return self._build_result(
                scenario=scenario,
                state=state,
                workflow_run=workflow_run,
                retry_decisions=retry_decisions,
            )

        if scenario == ReplayScenario.RETRY_EXHAUSTION:
            while True:
                decisions = self._request_retries_for_correction_handoffs(
                    workflow_run=workflow_run,
                    state=state,
                    result=qa_result,
                )
                retry_decisions.extend(decisions)
                if any(not decision.retry_allowed for decision in decisions):
                    return self._build_result(
                        scenario=scenario,
                        state=state,
                        workflow_run=workflow_run,
                        retry_decisions=retry_decisions,
                    )
                qa_result = await self._run_agent(
                    workflow_run=workflow_run,
                    state=state,
                    context=context,
                    agent=QAValidationAgent(),
                    handoff=state.latest_handoff,
                )

        await self._run_successful_downstream(
            workflow_run=workflow_run,
            state=state,
            context=context,
            qa_result=qa_result,
        )
        self.runtime.update_workflow_status(
            workflow_run=workflow_run,
            state=state,
            status=WorkflowStateStatus.COMPLETED,
            stage=WorkflowStage.COMPLETED,
            current_agent=BUSINESS_INSIGHT_AGENT,
        )
        return self._build_result(
            scenario=scenario,
            state=state,
            workflow_run=workflow_run,
            retry_decisions=retry_decisions,
        )

    async def _run_until_qa(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        context: AgentExecutionContext,
        inject_validation_error: bool,
    ) -> AgentRunResult:
        """Run document preparation, extraction, assembly, and QA."""

        intake_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=DocumentIntakeAgent(),
        )
        if is_terminal_agent_result(intake_result):
            return intake_result
        layout_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=DocumentLayoutAnalyzerAgent(),
            handoff=self._handoff_to(intake_result, DOCUMENT_LAYOUT_ANALYZER_AGENT),
        )
        if is_terminal_agent_result(layout_result):
            return layout_result
        privacy_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=PrivacyPolicyGateAgent(),
            handoff=self._handoff_to(layout_result, PRIVACY_POLICY_GATE_AGENT),
        )
        if is_terminal_agent_result(privacy_result):
            return privacy_result

        metadata_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=MetadataExtractorAgent(),
            handoff=self._handoff_to(privacy_result, METADATA_EXTRACTOR_AGENT),
        )
        if is_terminal_agent_result(metadata_result):
            return metadata_result

        table_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=TableExtractorAgent(),
            handoff=self._handoff_to(privacy_result, TABLE_EXTRACTOR_AGENT),
        )
        if is_terminal_agent_result(table_result):
            return table_result

        totals_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=TotalsExtractorAgent(),
            handoff=self._handoff_to(privacy_result, TOTALS_EXTRACTOR_AGENT),
        )
        if is_terminal_agent_result(totals_result):
            return totals_result

        assembly_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=InvoiceAssemblyNode(),
        )
        if inject_validation_error:
            state.qa_error_signals.append(
                create_total_amount_correction_signal(
                    expected_value="110.00",
                    observed_value="120.00",
                    evidence_refs=["page:1:bbox:300,700,520,760"],
                )
            )
        return await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=QAValidationAgent(),
            handoff=self._handoff_to(assembly_result, QA_VALIDATION_AGENT),
        )

    async def _run_successful_downstream(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        context: AgentExecutionContext,
        qa_result: AgentRunResult,
    ) -> None:
        """Run classification, reconciliation, review, and insight agents."""

        classification_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=ClassificationAgent(),
            handoff=self._handoff_to(qa_result, CLASSIFICATION_AGENT),
        )
        if (
            is_terminal_agent_result(classification_result)
            or not classification_result.handoffs
        ):
            return

        reconciliation_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=ReconciliationAgent(),
            handoff=classification_result.handoffs[0],
        )
        if (
            is_terminal_agent_result(reconciliation_result)
            or not reconciliation_result.handoffs
        ):
            return

        review_result = await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=ReviewCoordinatorAgent(),
            handoff=reconciliation_result.handoffs[0],
        )
        if is_terminal_agent_result(review_result) or not review_result.handoffs:
            return

        await self._run_agent(
            workflow_run=workflow_run,
            state=state,
            context=context,
            agent=BusinessInsightAgent(),
            handoff=review_result.handoffs[0],
        )

    async def _run_agent(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        context: AgentExecutionContext,
        agent: BaseAgent,
        handoff: AgentHandoffEnvelope | None = None,
    ) -> AgentRunResult:
        """Run one agent and persist the step plus all outgoing handoffs."""

        started_at = perf_counter()
        result = await agent.run(state=state, context=context, handoff=handoff)
        result.metrics.setdefault(
            "duration_ms",
            round((perf_counter() - started_at) * 1000, 2),
        )
        step = self.runtime.record_agent_step(
            workflow_run=workflow_run,
            state=state,
            agent_name=agent.definition.name,
            result=result,
            attempt=context.attempt,
        )
        self.step_executions.append(step)
        for envelope in result.handoffs:
            recorded_handoff = self.runtime.record_handoff(
                workflow_run=workflow_run,
                state=state,
                envelope=envelope,
                source_step=step,
            )
            self.handoffs.append(recorded_handoff)
        return result

    def _request_retries_for_correction_handoffs(
        self,
        *,
        workflow_run: WorkflowRun,
        state: WorkflowState,
        result: AgentRunResult,
    ) -> list[RetryDecision]:
        """Increment retry counters for correction handoffs emitted by QA."""

        decisions: list[RetryDecision] = []
        for handoff in result.handoffs:
            if handoff.handoff_type != HandoffType.CORRECTION:
                continue
            decisions.append(
                self.runtime.request_retry(
                    workflow_run=workflow_run,
                    state=state,
                    agent_name=handoff.target_agent,
                    error_code="RETRY_EXHAUSTED",
                    error_message=(
                        "Workflow replay exhausted correction retries for "
                        f"{handoff.target_agent}."
                    ),
                )
            )
        return decisions

    def _build_result(
        self,
        *,
        scenario: ReplayScenario,
        state: WorkflowState,
        workflow_run: WorkflowRun,
        retry_decisions: list[RetryDecision],
    ) -> WorkflowReplayResult:
        """Build an immutable result snapshot for callers and tests."""

        return WorkflowReplayResult(
            scenario=scenario,
            state=state,
            workflow_run=workflow_run,
            step_executions=list(self.step_executions),
            handoffs=list(self.handoffs),
            retry_decisions=list(retry_decisions),
        )

    @staticmethod
    def _handoff_to(
        result: AgentRunResult,
        target_agent: str,
    ) -> AgentHandoffEnvelope:
        """Return the first handoff targeting a given agent."""

        for handoff in result.handoffs:
            if handoff.target_agent == target_agent:
                return handoff
        raise ValueError(f"No handoff found for target agent '{target_agent}'.")


def replay_result_to_summary(result: WorkflowReplayResult) -> dict[str, object]:
    """Return a JSON-compatible summary for CLI output."""

    return {
        "scenario": result.scenario.value,
        "workflow_run_id": str(result.workflow_run.id),
        "tenant_id": str(result.state.tenant_id),
        "document_id": str(result.state.document_id),
        "status": result.state.status.value,
        "stage": result.state.stage.value,
        "current_agent": result.state.current_agent,
        "completed_agents": result.state.completed_agents,
        "retry_counts": result.state.retry_counts,
        "step_count": len(result.step_executions),
        "handoff_count": len(result.handoffs),
        "retry_decisions": [
            {
                "agent_name": decision.agent_name,
                "retry_count": decision.retry_count,
                "max_retries": decision.max_retries,
                "retry_allowed": decision.retry_allowed,
                "workflow_status": decision.workflow_status.value,
                "error_code": decision.error_code,
                "error_message": decision.error_message,
            }
            for decision in result.retry_decisions
        ],
    }


def is_terminal_agent_result(result: AgentRunResult) -> bool:
    """Return whether a result should stop the replay flow immediately."""

    return result.status in {
        AgentRunStatus.FAILED,
        AgentRunStatus.REVIEW_REQUIRED,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for local workflow replay."""

    parser = argparse.ArgumentParser(
        description="Replay the skeleton multi-agent workflow locally.",
    )
    parser.add_argument(
        "--document-id",
        type=UUID,
        required=True,
        help="Document UUID to place into the replay workflow state.",
    )
    parser.add_argument(
        "--tenant-id",
        type=UUID,
        default=uuid4(),
        help="Tenant UUID to place into the replay workflow state.",
    )
    parser.add_argument(
        "--scenario",
        choices=[scenario.value for scenario in ReplayScenario],
        default=ReplayScenario.HAPPY_PATH.value,
        help="Replay scenario to execute.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Retry budget for correction loops.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run workflow replay from the command line."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    state = create_replay_state(
        tenant_id=cast(UUID, args.tenant_id),
        document_id=cast(UUID, args.document_id),
        max_retries=cast(int, args.max_retries),
    )
    result = asyncio.run(
        WorkflowReplayRunner().run(
            state=state,
            scenario=ReplayScenario(cast(str, args.scenario)),
            correlation_id="local-replay",
        )
    )
    print(json.dumps(replay_result_to_summary(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
