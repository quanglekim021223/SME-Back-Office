"""LangGraph adapter for workflow agents.

This module keeps LangGraph behind the existing workflow contracts. The current
runtime still owns persistence for workflow runs, agent steps, and handoffs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypedDict, cast

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
    WorkflowState,
    WorkflowStateStatus,
)
from app.workflows.document_preparation import (
    DOCUMENT_INTAKE_AGENT,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    METADATA_EXTRACTOR_AGENT,
    PRIVACY_POLICY_GATE_AGENT,
    TABLE_EXTRACTOR_AGENT,
    TOTALS_EXTRACTOR_AGENT,
    DocumentIntakeAgent,
    DocumentLayoutAnalyzerAgent,
    PrivacyPolicyGateAgent,
)
from app.workflows.invoice_extraction import (
    INVOICE_ASSEMBLY_NODE,
    QA_VALIDATION_AGENT,
    InvoiceAssemblyNode,
    MetadataExtractorAgent,
    QAValidationAgent,
    TableExtractorAgent,
    TotalsExtractorAgent,
)
from app.workflows.runtime import RetryDecision, WorkflowRuntimeService

LANGGRAPH_RETRY_GATE_NODE = "langgraph_retry_gate"


class LangGraphDocumentPreparationState(TypedDict):
    """State passed between LangGraph document-preparation nodes."""

    workflow_state: WorkflowState
    workflow_run: WorkflowRun
    context: AgentExecutionContext
    latest_result: AgentRunResult | None
    results_by_agent: dict[str, AgentRunResult]
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]
    retry_allowed: bool
    retry_target_agent: str | None
    retry_decisions: list[RetryDecision]
    checkpoints: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class LangGraphWorkflowResult:
    """Result returned by the LangGraph workflow adapter."""

    state: WorkflowState
    workflow_run: WorkflowRun
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]
    retry_decisions: list[RetryDecision]
    checkpoints: list[dict[str, object]]
    used_langgraph: bool


class LangGraphWorkflowAdapter:
    """Graph adapter that reuses existing workflow agents and persistence."""

    def __init__(self, runtime: WorkflowRuntimeService) -> None:
        self.runtime = runtime

    async def run_document_preparation(
        self,
        *,
        state: WorkflowState,
        workflow_run: WorkflowRun,
        context: AgentExecutionContext,
        require_langgraph: bool = False,
    ) -> LangGraphWorkflowResult:
        """Run document intake, privacy gate, and layout analysis as graph nodes."""

        graph_state = _initial_graph_state(
            state=state,
            workflow_run=workflow_run,
            context=context,
        )

        if is_langgraph_available():
            final_state = await self._run_document_preparation_graph(graph_state)
            return _build_result(final_state, used_langgraph=True)

        if require_langgraph:
            raise RuntimeError(
                "LangGraph is not installed in this environment. Install backend "
                "dependencies before requiring the graph adapter."
            )

        final_state = await self._run_document_preparation_fallback(graph_state)
        return _build_result(final_state, used_langgraph=False)

    async def run_invoice_extraction_until_qa(
        self,
        *,
        state: WorkflowState,
        workflow_run: WorkflowRun,
        context: AgentExecutionContext,
        require_langgraph: bool = False,
    ) -> LangGraphWorkflowResult:
        """Run document preparation, invoice extraction, assembly, and QA nodes."""

        graph_state = _initial_graph_state(
            state=state,
            workflow_run=workflow_run,
            context=context,
        )

        if is_langgraph_available():
            final_state = await self._run_invoice_extraction_graph(graph_state)
            return _build_result(final_state, used_langgraph=True)

        if require_langgraph:
            raise RuntimeError(
                "LangGraph is not installed in this environment. Install backend "
                "dependencies before requiring the graph adapter."
            )

        final_state = await self._run_invoice_extraction_fallback(graph_state)
        return _build_result(final_state, used_langgraph=False)

    async def _run_document_preparation_graph(
        self,
        graph_state: LangGraphDocumentPreparationState,
    ) -> LangGraphDocumentPreparationState:
        """Compile and run the document-preparation graph with lazy imports."""

        from langgraph.graph import END
        from langgraph.graph import StateGraph as RawStateGraph

        StateGraph = cast(Any, RawStateGraph)
        builder = StateGraph(LangGraphDocumentPreparationState)
        builder.add_node(
            DOCUMENT_INTAKE_AGENT,
            self._node(
                DocumentIntakeAgent(),
                handoff_target=None,
            ),
        )
        builder.add_node(
            DOCUMENT_LAYOUT_ANALYZER_AGENT,
            self._node(
                DocumentLayoutAnalyzerAgent(),
                handoff_target=DOCUMENT_LAYOUT_ANALYZER_AGENT,
                handoff_source_agent=DOCUMENT_INTAKE_AGENT,
            ),
        )
        builder.add_node(
            PRIVACY_POLICY_GATE_AGENT,
            self._node(
                PrivacyPolicyGateAgent(),
                handoff_target=PRIVACY_POLICY_GATE_AGENT,
                handoff_source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            ),
        )

        builder.set_entry_point(DOCUMENT_INTAKE_AGENT)
        builder.add_conditional_edges(
            DOCUMENT_INTAKE_AGENT,
            _route_after(DOCUMENT_LAYOUT_ANALYZER_AGENT),
            {
                DOCUMENT_LAYOUT_ANALYZER_AGENT: DOCUMENT_LAYOUT_ANALYZER_AGENT,
                "end": END,
            },
        )
        builder.add_conditional_edges(
            DOCUMENT_LAYOUT_ANALYZER_AGENT,
            _route_after(PRIVACY_POLICY_GATE_AGENT),
            {
                PRIVACY_POLICY_GATE_AGENT: PRIVACY_POLICY_GATE_AGENT,
                "end": END,
            },
        )
        builder.add_edge(PRIVACY_POLICY_GATE_AGENT, END)

        compiled = builder.compile()
        result = await compiled.ainvoke(graph_state)
        return cast(LangGraphDocumentPreparationState, result)

    async def _run_invoice_extraction_graph(
        self,
        graph_state: LangGraphDocumentPreparationState,
    ) -> LangGraphDocumentPreparationState:
        """Compile and run the invoice extraction graph with lazy imports."""

        from langgraph.graph import END
        from langgraph.graph import StateGraph as RawStateGraph

        StateGraph = cast(Any, RawStateGraph)
        builder = StateGraph(LangGraphDocumentPreparationState)
        self._add_document_preparation_nodes(builder)
        self._add_invoice_extraction_nodes(builder)
        builder.add_node(LANGGRAPH_RETRY_GATE_NODE, self._retry_gate_node)

        builder.set_entry_point(DOCUMENT_INTAKE_AGENT)
        self._add_conditional_next_edge(
            builder,
            source=DOCUMENT_INTAKE_AGENT,
            next_node=PRIVACY_POLICY_GATE_AGENT,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=PRIVACY_POLICY_GATE_AGENT,
            next_node=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            next_node=METADATA_EXTRACTOR_AGENT,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=METADATA_EXTRACTOR_AGENT,
            next_node=TABLE_EXTRACTOR_AGENT,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=TABLE_EXTRACTOR_AGENT,
            next_node=TOTALS_EXTRACTOR_AGENT,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=TOTALS_EXTRACTOR_AGENT,
            next_node=INVOICE_ASSEMBLY_NODE,
            end_node=END,
        )
        self._add_conditional_next_edge(
            builder,
            source=INVOICE_ASSEMBLY_NODE,
            next_node=QA_VALIDATION_AGENT,
            end_node=END,
        )
        builder.add_conditional_edges(
            QA_VALIDATION_AGENT,
            _route_after_qa,
            {
                "valid": END,
                "retry": LANGGRAPH_RETRY_GATE_NODE,
                "review_required": END,
                "failed": END,
            },
        )
        builder.add_conditional_edges(
            LANGGRAPH_RETRY_GATE_NODE,
            _route_after_retry_gate,
            {
                METADATA_EXTRACTOR_AGENT: METADATA_EXTRACTOR_AGENT,
                TABLE_EXTRACTOR_AGENT: TABLE_EXTRACTOR_AGENT,
                TOTALS_EXTRACTOR_AGENT: TOTALS_EXTRACTOR_AGENT,
                "exhausted": END,
                "failed": END,
            },
        )

        compiled = builder.compile()
        result = await compiled.ainvoke(graph_state)
        return cast(LangGraphDocumentPreparationState, result)

    async def _run_document_preparation_fallback(
        self,
        graph_state: LangGraphDocumentPreparationState,
    ) -> LangGraphDocumentPreparationState:
        """Run the same graph nodes directly when LangGraph is unavailable."""

        for agent, handoff_target in (
            (DocumentIntakeAgent(), None),
            (DocumentLayoutAnalyzerAgent(), DOCUMENT_LAYOUT_ANALYZER_AGENT),
            (PrivacyPolicyGateAgent(), PRIVACY_POLICY_GATE_AGENT),
        ):
            graph_state = await self._run_agent_node(
                graph_state,
                agent=agent,
                handoff_target=handoff_target,
                handoff_source_agent=None,
            )
            if _is_terminal_result(graph_state["latest_result"]):
                break
        return graph_state

    async def _run_invoice_extraction_fallback(
        self,
        graph_state: LangGraphDocumentPreparationState,
    ) -> LangGraphDocumentPreparationState:
        """Run invoice extraction nodes directly when LangGraph is unavailable."""

        graph_state = await self._run_invoice_extraction_segment(
            graph_state,
            segment="full",
        )

        while _route_after_qa(graph_state) == "retry":
            graph_state = self._retry_gate_node(graph_state)
            if not graph_state["retry_allowed"]:
                break
            graph_state = await self._run_invoice_extraction_segment(
                graph_state,
                segment=graph_state["retry_target_agent"],
            )

        return graph_state

    async def _run_invoice_extraction_segment(
        self,
        graph_state: LangGraphDocumentPreparationState,
        *,
        segment: str | None,
    ) -> LangGraphDocumentPreparationState:
        """Run a full or targeted invoice extraction segment without LangGraph."""

        node_plan = {
            "full": (
                (DocumentIntakeAgent(), None, None),
                (
                    DocumentLayoutAnalyzerAgent(),
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                    DOCUMENT_INTAKE_AGENT,
                ),
                (
                    PrivacyPolicyGateAgent(),
                    PRIVACY_POLICY_GATE_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (
                    MetadataExtractorAgent(),
                    METADATA_EXTRACTOR_AGENT,
                    PRIVACY_POLICY_GATE_AGENT,
                ),
                (
                    TableExtractorAgent(),
                    TABLE_EXTRACTOR_AGENT,
                    PRIVACY_POLICY_GATE_AGENT,
                ),
                (
                    TotalsExtractorAgent(),
                    TOTALS_EXTRACTOR_AGENT,
                    PRIVACY_POLICY_GATE_AGENT,
                ),
                (InvoiceAssemblyNode(), None, None),
                (QAValidationAgent(), QA_VALIDATION_AGENT, INVOICE_ASSEMBLY_NODE),
            ),
            METADATA_EXTRACTOR_AGENT: (
                (
                    MetadataExtractorAgent(),
                    METADATA_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (
                    TableExtractorAgent(),
                    TABLE_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (
                    TotalsExtractorAgent(),
                    TOTALS_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (InvoiceAssemblyNode(), None, None),
                (QAValidationAgent(), QA_VALIDATION_AGENT, INVOICE_ASSEMBLY_NODE),
            ),
            TABLE_EXTRACTOR_AGENT: (
                (
                    TableExtractorAgent(),
                    TABLE_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (
                    TotalsExtractorAgent(),
                    TOTALS_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (InvoiceAssemblyNode(), None, None),
                (QAValidationAgent(), QA_VALIDATION_AGENT, INVOICE_ASSEMBLY_NODE),
            ),
            TOTALS_EXTRACTOR_AGENT: (
                (
                    TotalsExtractorAgent(),
                    TOTALS_EXTRACTOR_AGENT,
                    DOCUMENT_LAYOUT_ANALYZER_AGENT,
                ),
                (InvoiceAssemblyNode(), None, None),
                (QAValidationAgent(), QA_VALIDATION_AGENT, INVOICE_ASSEMBLY_NODE),
            ),
        }

        for agent, handoff_target, handoff_source_agent in node_plan.get(
            segment or "",
            (),
        ):
            graph_state = await self._run_agent_node(
                graph_state,
                agent=agent,
                handoff_target=handoff_target,
                handoff_source_agent=handoff_source_agent,
            )
            if _is_terminal_result(graph_state["latest_result"]):
                break
        return graph_state

    def _add_document_preparation_nodes(self, builder: Any) -> None:
        """Add document preparation agents as graph nodes."""

        builder.add_node(
            DOCUMENT_INTAKE_AGENT,
            self._node(
                DocumentIntakeAgent(),
                handoff_target=None,
            ),
        )
        builder.add_node(
            PRIVACY_POLICY_GATE_AGENT,
            self._node(
                PrivacyPolicyGateAgent(),
                handoff_target=PRIVACY_POLICY_GATE_AGENT,
                handoff_source_agent=DOCUMENT_INTAKE_AGENT,
            ),
        )
        builder.add_node(
            DOCUMENT_LAYOUT_ANALYZER_AGENT,
            self._node(
                DocumentLayoutAnalyzerAgent(),
                handoff_target=DOCUMENT_LAYOUT_ANALYZER_AGENT,
                handoff_source_agent=PRIVACY_POLICY_GATE_AGENT,
            ),
        )

    def _add_invoice_extraction_nodes(self, builder: Any) -> None:
        """Add invoice extraction, assembly, and QA agents as graph nodes."""

        builder.add_node(
            METADATA_EXTRACTOR_AGENT,
            self._node(
                MetadataExtractorAgent(),
                handoff_target=METADATA_EXTRACTOR_AGENT,
                handoff_source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            ),
        )
        builder.add_node(
            TABLE_EXTRACTOR_AGENT,
            self._node(
                TableExtractorAgent(),
                handoff_target=TABLE_EXTRACTOR_AGENT,
                handoff_source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            ),
        )
        builder.add_node(
            TOTALS_EXTRACTOR_AGENT,
            self._node(
                TotalsExtractorAgent(),
                handoff_target=TOTALS_EXTRACTOR_AGENT,
                handoff_source_agent=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            ),
        )
        builder.add_node(
            INVOICE_ASSEMBLY_NODE,
            self._node(InvoiceAssemblyNode(), handoff_target=None),
        )
        builder.add_node(
            QA_VALIDATION_AGENT,
            self._node(
                QAValidationAgent(),
                handoff_target=QA_VALIDATION_AGENT,
                handoff_source_agent=INVOICE_ASSEMBLY_NODE,
            ),
        )

    def _add_conditional_next_edge(
        self,
        builder: Any,
        *,
        source: str,
        next_node: str,
        end_node: str,
    ) -> None:
        """Add a standard edge that stops on failed or review-required results."""

        builder.add_conditional_edges(
            source,
            _route_after(next_node),
            {
                next_node: next_node,
                "end": end_node,
            },
        )

    def _node(
        self,
        agent: BaseAgent,
        *,
        handoff_target: str | None,
        handoff_source_agent: str | None = None,
    ) -> Callable[
        [LangGraphDocumentPreparationState],
        Awaitable[LangGraphDocumentPreparationState],
    ]:
        """Return a LangGraph-compatible async node for one existing agent."""

        async def run_node(
            graph_state: LangGraphDocumentPreparationState,
        ) -> LangGraphDocumentPreparationState:
            return await self._run_agent_node(
                graph_state,
                agent=agent,
                handoff_target=handoff_target,
                handoff_source_agent=handoff_source_agent,
            )

        return run_node

    async def _run_agent_node(
        self,
        graph_state: LangGraphDocumentPreparationState,
        *,
        agent: BaseAgent,
        handoff_target: str | None,
        handoff_source_agent: str | None,
    ) -> LangGraphDocumentPreparationState:
        """Run one existing agent and persist its step and outgoing handoffs."""

        state = graph_state["workflow_state"]
        workflow_run = graph_state["workflow_run"]
        latest_result = graph_state["latest_result"]
        source_result = (
            latest_result
            if handoff_target is not None
            and _result_has_handoff_to(latest_result, handoff_target)
            else (
                latest_result
                if handoff_source_agent is None
                else graph_state["results_by_agent"].get(handoff_source_agent)
            )
        )
        result = await agent.run(
            state=state,
            context=graph_state["context"],
            handoff=_handoff_to(source_result, handoff_target),
        )
        step = self.runtime.record_agent_step(
            workflow_run=workflow_run,
            state=state,
            agent_name=agent.definition.name,
            result=result,
            attempt=graph_state["context"].attempt,
        )

        recorded_handoffs: list[AgentHandoff] = []
        for envelope in result.handoffs:
            recorded_handoffs.append(
                self.runtime.record_handoff(
                    workflow_run=workflow_run,
                    state=state,
                    envelope=envelope,
                    source_step=step,
                )
            )

        step_executions = [*graph_state["step_executions"], step]
        handoffs = [*graph_state["handoffs"], *recorded_handoffs]

        return LangGraphDocumentPreparationState(
            workflow_state=state,
            workflow_run=workflow_run,
            context=graph_state["context"],
            latest_result=result,
            results_by_agent={
                **graph_state["results_by_agent"],
                agent.definition.name: result,
            },
            step_executions=step_executions,
            handoffs=handoffs,
            retry_allowed=graph_state["retry_allowed"],
            retry_target_agent=graph_state["retry_target_agent"],
            retry_decisions=graph_state["retry_decisions"],
            checkpoints=[
                *graph_state["checkpoints"],
                _checkpoint(
                    label=agent.definition.name,
                    state=state,
                    step_count=len(step_executions),
                    handoff_count=len(handoffs),
                    latest_result=result,
                ),
            ],
        )

    def _retry_gate_node(
        self,
        graph_state: LangGraphDocumentPreparationState,
    ) -> LangGraphDocumentPreparationState:
        """Increment retry state and route QA correction to its target agent."""

        state = graph_state["workflow_state"]
        workflow_run = graph_state["workflow_run"]
        latest_result = graph_state["latest_result"]
        correction_handoff = _first_correction_handoff(latest_result)
        if correction_handoff is None:
            return cast(
                LangGraphDocumentPreparationState,
                {
                    **graph_state,
                    "retry_allowed": False,
                    "retry_target_agent": None,
                    "checkpoints": [
                        *graph_state["checkpoints"],
                        _checkpoint(
                            label=LANGGRAPH_RETRY_GATE_NODE,
                            state=state,
                            step_count=len(graph_state["step_executions"]),
                            handoff_count=len(graph_state["handoffs"]),
                            latest_result=latest_result,
                            retry_allowed=False,
                            retry_target_agent=None,
                        ),
                    ],
                },
            )

        decision = self.runtime.request_retry(
            workflow_run=workflow_run,
            state=state,
            agent_name=correction_handoff.target_agent,
            error_code="RETRY_EXHAUSTED",
            error_message=(
                f"Retry budget exhausted for agent '{correction_handoff.target_agent}'."
            ),
        )

        return cast(
            LangGraphDocumentPreparationState,
            {
                **graph_state,
                "retry_allowed": decision.retry_allowed,
                "retry_target_agent": (
                    correction_handoff.target_agent if decision.retry_allowed else None
                ),
                "retry_decisions": [*graph_state["retry_decisions"], decision],
                "checkpoints": [
                    *graph_state["checkpoints"],
                    _checkpoint(
                        label=LANGGRAPH_RETRY_GATE_NODE,
                        state=state,
                        step_count=len(graph_state["step_executions"]),
                        handoff_count=len(graph_state["handoffs"]),
                        latest_result=latest_result,
                        retry_allowed=decision.retry_allowed,
                        retry_target_agent=correction_handoff.target_agent,
                    ),
                ],
            },
        )


def is_langgraph_available() -> bool:
    """Return whether LangGraph can be imported in the current environment."""

    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


def _initial_graph_state(
    *,
    state: WorkflowState,
    workflow_run: WorkflowRun,
    context: AgentExecutionContext,
) -> LangGraphDocumentPreparationState:
    """Build the initial graph state for any LangGraph adapter run."""

    return LangGraphDocumentPreparationState(
        workflow_state=state,
        workflow_run=workflow_run,
        context=context,
        latest_result=None,
        results_by_agent={},
        step_executions=[],
        handoffs=[],
        retry_allowed=True,
        retry_target_agent=None,
        retry_decisions=[],
        checkpoints=[],
    )


def _build_result(
    graph_state: LangGraphDocumentPreparationState,
    *,
    used_langgraph: bool,
) -> LangGraphWorkflowResult:
    """Build a stable result object from graph state."""

    return LangGraphWorkflowResult(
        state=graph_state["workflow_state"],
        workflow_run=graph_state["workflow_run"],
        step_executions=list(graph_state["step_executions"]),
        handoffs=list(graph_state["handoffs"]),
        retry_decisions=list(graph_state["retry_decisions"]),
        checkpoints=list(graph_state["checkpoints"]),
        used_langgraph=used_langgraph,
    )


def _handoff_to(
    result: AgentRunResult | None,
    target_agent: str | None,
) -> AgentHandoffEnvelope | None:
    """Return the first handoff targeting an agent, if the node needs one."""

    if result is None or target_agent is None:
        return None
    for handoff in result.handoffs:
        if handoff.target_agent == target_agent:
            return handoff
    raise ValueError(f"No handoff found for target agent '{target_agent}'.")


def _first_correction_handoff(
    result: AgentRunResult | None,
) -> AgentHandoffEnvelope | None:
    """Return the first targeted correction handoff from a retry result."""

    if result is None:
        return None
    for handoff in result.handoffs:
        if handoff.handoff_type == HandoffType.CORRECTION:
            return handoff
    return None


def _result_has_handoff_to(
    result: AgentRunResult | None,
    target_agent: str,
) -> bool:
    """Return whether an agent result has a handoff to the target agent."""

    if result is None:
        return False
    return any(handoff.target_agent == target_agent for handoff in result.handoffs)


def _checkpoint(
    *,
    label: str,
    state: WorkflowState,
    step_count: int,
    handoff_count: int,
    latest_result: AgentRunResult | None,
    retry_allowed: bool | None = None,
    retry_target_agent: str | None = None,
) -> dict[str, object]:
    """Build a small local debug checkpoint without sensitive payload bodies."""

    checkpoint: dict[str, object] = {
        "label": label,
        "workflow_status": state.status.value,
        "stage": state.stage.value,
        "current_agent": state.current_agent,
        "completed_agents": list(state.completed_agents),
        "retry_counts": dict(state.retry_counts),
        "step_count": step_count,
        "handoff_count": handoff_count,
    }
    if latest_result is not None:
        checkpoint["result_status"] = latest_result.status.value
        checkpoint["result_error_code"] = latest_result.error_code
    if retry_allowed is not None:
        checkpoint["retry_allowed"] = retry_allowed
        checkpoint["retry_target_agent"] = retry_target_agent
    return checkpoint


def _is_terminal_result(result: AgentRunResult | None) -> bool:
    """Return whether a node result should stop the graph early."""

    if result is None:
        return False
    return result.status in {
        AgentRunStatus.FAILED,
        AgentRunStatus.REVIEW_REQUIRED,
    }


def _route_after(next_node: str) -> Callable[[Mapping[str, Any]], str]:
    """Return a small conditional edge router for graph nodes."""

    def route(graph_state: Mapping[str, Any]) -> str:
        latest_result = graph_state.get("latest_result")
        if _is_terminal_result(latest_result):
            return "end"
        return next_node

    return route


def _route_after_qa(graph_state: Mapping[str, Any]) -> str:
    """Route the QA result to a named outcome edge."""

    latest_result = graph_state.get("latest_result")
    if not isinstance(latest_result, AgentRunResult):
        return "failed"
    if latest_result.status == AgentRunStatus.SUCCEEDED:
        return "valid"
    if latest_result.status == AgentRunStatus.RETRY_REQUESTED:
        return "retry"
    if latest_result.status == AgentRunStatus.REVIEW_REQUIRED:
        return "review_required"
    return "failed"


def _route_after_retry_gate(graph_state: Mapping[str, Any]) -> str:
    """Route retry gate output to the targeted extractor or terminal edge."""

    workflow_state = graph_state.get("workflow_state")
    if (
        isinstance(workflow_state, WorkflowState)
        and workflow_state.status == WorkflowStateStatus.DEAD_LETTERED
    ):
        return "exhausted"

    if not graph_state.get("retry_allowed"):
        return "exhausted"

    retry_target_agent = graph_state.get("retry_target_agent")
    if retry_target_agent in {
        METADATA_EXTRACTOR_AGENT,
        TABLE_EXTRACTOR_AGENT,
        TOTALS_EXTRACTOR_AGENT,
    }:
        return str(retry_target_agent)
    return "failed"
