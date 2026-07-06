"""LangGraph adapter for workflow agents.

This module keeps LangGraph behind the existing workflow contracts. The current
runtime still owns persistence for workflow runs, agent steps, and handoffs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.workflows.agents import (
    AgentExecutionContext,
    AgentRunResult,
    AgentRunStatus,
    BaseAgent,
)
from app.workflows.contracts import AgentHandoffEnvelope, WorkflowState
from app.workflows.document_preparation import (
    DOCUMENT_INTAKE_AGENT,
    DOCUMENT_LAYOUT_ANALYZER_AGENT,
    PRIVACY_POLICY_GATE_AGENT,
    DocumentIntakeAgent,
    DocumentLayoutAnalyzerAgent,
    PrivacyPolicyGateAgent,
)
from app.workflows.runtime import WorkflowRuntimeService


class LangGraphDocumentPreparationState(TypedDict):
    """State passed between LangGraph document-preparation nodes."""

    workflow_state: WorkflowState
    workflow_run: WorkflowRun
    context: AgentExecutionContext
    latest_result: AgentRunResult | None
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]


@dataclass(frozen=True, slots=True)
class LangGraphWorkflowResult:
    """Result returned by the LangGraph workflow adapter."""

    state: WorkflowState
    workflow_run: WorkflowRun
    step_executions: list[AgentStepExecution]
    handoffs: list[AgentHandoff]
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

        graph_state = LangGraphDocumentPreparationState(
            workflow_state=state,
            workflow_run=workflow_run,
            context=context,
            latest_result=None,
            step_executions=[],
            handoffs=[],
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
            self._node(DocumentIntakeAgent(), handoff_target=None),
        )
        builder.add_node(
            PRIVACY_POLICY_GATE_AGENT,
            self._node(
                PrivacyPolicyGateAgent(),
                handoff_target=PRIVACY_POLICY_GATE_AGENT,
            ),
        )
        builder.add_node(
            DOCUMENT_LAYOUT_ANALYZER_AGENT,
            self._node(
                DocumentLayoutAnalyzerAgent(),
                handoff_target=DOCUMENT_LAYOUT_ANALYZER_AGENT,
            ),
        )

        builder.set_entry_point(DOCUMENT_INTAKE_AGENT)
        builder.add_conditional_edges(
            DOCUMENT_INTAKE_AGENT,
            _route_after(PRIVACY_POLICY_GATE_AGENT),
            {
                PRIVACY_POLICY_GATE_AGENT: PRIVACY_POLICY_GATE_AGENT,
                "end": END,
            },
        )
        builder.add_conditional_edges(
            PRIVACY_POLICY_GATE_AGENT,
            _route_after(DOCUMENT_LAYOUT_ANALYZER_AGENT),
            {
                DOCUMENT_LAYOUT_ANALYZER_AGENT: DOCUMENT_LAYOUT_ANALYZER_AGENT,
                "end": END,
            },
        )
        builder.add_edge(DOCUMENT_LAYOUT_ANALYZER_AGENT, END)

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
            (PrivacyPolicyGateAgent(), PRIVACY_POLICY_GATE_AGENT),
            (DocumentLayoutAnalyzerAgent(), DOCUMENT_LAYOUT_ANALYZER_AGENT),
        ):
            graph_state = await self._run_agent_node(
                graph_state,
                agent=agent,
                handoff_target=handoff_target,
            )
            if _is_terminal_result(graph_state["latest_result"]):
                break
        return graph_state

    def _node(
        self,
        agent: BaseAgent,
        *,
        handoff_target: str | None,
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
            )

        return run_node

    async def _run_agent_node(
        self,
        graph_state: LangGraphDocumentPreparationState,
        *,
        agent: BaseAgent,
        handoff_target: str | None,
    ) -> LangGraphDocumentPreparationState:
        """Run one existing agent and persist its step and outgoing handoffs."""

        state = graph_state["workflow_state"]
        workflow_run = graph_state["workflow_run"]
        result = await agent.run(
            state=state,
            context=graph_state["context"],
            handoff=_handoff_to(graph_state["latest_result"], handoff_target),
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

        return LangGraphDocumentPreparationState(
            workflow_state=state,
            workflow_run=workflow_run,
            context=graph_state["context"],
            latest_result=result,
            step_executions=[*graph_state["step_executions"], step],
            handoffs=[*graph_state["handoffs"], *recorded_handoffs],
        )


def is_langgraph_available() -> bool:
    """Return whether LangGraph can be imported in the current environment."""

    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


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


def _is_terminal_result(result: AgentRunResult | None) -> bool:
    """Return whether a node result should stop the graph early."""

    if result is None:
        return False
    return result.status in {
        AgentRunStatus.FAILED,
        AgentRunStatus.REVIEW_REQUIRED,
    }


def _route_after(next_node: str) -> Callable[[dict[str, Any]], str]:
    """Return a small conditional edge router for graph nodes."""

    def route(graph_state: dict[str, Any]) -> str:
        latest_result = graph_state.get("latest_result")
        if _is_terminal_result(latest_result):
            return "end"
        return next_node

    return route
