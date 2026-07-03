"""Local evaluation runner and report generation for the backend foundation."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.evaluations.datasets import DEFAULT_DATASET_ID
from app.evaluations.scorers import (
    EvaluationCheck,
    EvaluationScore,
    build_score,
    check_exact,
    check_minimum_int,
)
from app.models.workflow import WorkflowRunStatus
from app.workflows.contracts import WorkflowStage, WorkflowStateStatus
from app.workflows.document_preparation import TOTALS_EXTRACTOR_AGENT
from app.workflows.replay import (
    ReplayScenario,
    WorkflowReplayResult,
    WorkflowReplayRunner,
    create_replay_state,
)

EVALUATION_REPORT_SCHEMA_VERSION = "evaluation.report.v1"
INITIAL_RELEASE_GATES_VERSION = "initial-release-gates.v1"


class EvaluationReleaseGate(BaseModel):
    """One release gate evaluated against scorer output."""

    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scorer_name: str = Field(min_length=1)
    threshold: float = Field(ge=0.0, le=1.0)
    actual_score: float = Field(ge=0.0, le=1.0)
    passed: bool


class EvaluationReport(BaseModel):
    """Machine-readable evaluation report emitted by the local runner."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVALUATION_REPORT_SCHEMA_VERSION
    generated_at: datetime
    dataset_id: str = Field(min_length=1)
    release_gates_version: str = INITIAL_RELEASE_GATES_VERSION
    passed: bool
    scores: list[EvaluationScore] = Field(default_factory=list)
    release_gates: list[EvaluationReleaseGate] = Field(default_factory=list)
    summary: dict[str, object] = Field(default_factory=dict)


async def run_evaluation_suite(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
) -> EvaluationReport:
    """Run the local deterministic evaluation suite."""

    workflow_score = await score_workflow_replay()
    return build_evaluation_report(
        dataset_id=dataset_id,
        scores=[workflow_score],
    )


async def score_workflow_replay() -> EvaluationScore:
    """Evaluate the skeleton workflow replay scenarios."""

    results: dict[ReplayScenario, WorkflowReplayResult] = {}
    for scenario in ReplayScenario:
        runner = WorkflowReplayRunner()
        state = create_replay_state(max_retries=3)
        results[scenario] = await runner.run(
            state=state,
            scenario=scenario,
            correlation_id=f"evaluation-{scenario.value}",
        )

    happy_path = results[ReplayScenario.HAPPY_PATH]
    failed_validation = results[ReplayScenario.FAILED_VALIDATION]
    retry_exhaustion = results[ReplayScenario.RETRY_EXHAUSTION]

    checks = [
        check_exact(
            "workflow_replay[happy_path].state_status",
            WorkflowStateStatus.COMPLETED.value,
            happy_path.state.status.value,
        ),
        check_exact(
            "workflow_replay[happy_path].workflow_status",
            WorkflowRunStatus.COMPLETED.value,
            happy_path.workflow_run.status,
        ),
        check_exact(
            "workflow_replay[happy_path].stage",
            WorkflowStage.COMPLETED.value,
            happy_path.state.stage.value,
        ),
        check_exact(
            "workflow_replay[happy_path].step_count",
            12,
            len(happy_path.step_executions),
        ),
        check_exact(
            "workflow_replay[happy_path].handoff_count",
            13,
            len(happy_path.handoffs),
        ),
        check_exact(
            "workflow_replay[failed_validation].state_status",
            WorkflowStateStatus.RUNNING.value,
            failed_validation.state.status.value,
        ),
        check_exact(
            "workflow_replay[failed_validation].stage",
            WorkflowStage.TOTALS_EXTRACTION.value,
            failed_validation.state.stage.value,
        ),
        check_exact(
            "workflow_replay[failed_validation].current_agent",
            TOTALS_EXTRACTOR_AGENT,
            failed_validation.state.current_agent,
        ),
        check_exact(
            "workflow_replay[failed_validation].retry_decision_count",
            1,
            len(failed_validation.retry_decisions),
        ),
        check_exact(
            "workflow_replay[failed_validation].retry_allowed",
            True,
            bool(
                failed_validation.retry_decisions
                and failed_validation.retry_decisions[0].retry_allowed
            ),
        ),
        check_exact(
            "workflow_replay[retry_exhaustion].state_status",
            WorkflowStateStatus.DEAD_LETTERED.value,
            retry_exhaustion.state.status.value,
        ),
        check_exact(
            "workflow_replay[retry_exhaustion].workflow_status",
            WorkflowRunStatus.DEAD_LETTERED.value,
            retry_exhaustion.workflow_run.status,
        ),
        check_exact(
            "workflow_replay[retry_exhaustion].stage",
            WorkflowStage.FAILED.value,
            retry_exhaustion.state.stage.value,
        ),
        check_minimum_int(
            "workflow_replay[retry_exhaustion].retry_decision_count",
            4,
            len(retry_exhaustion.retry_decisions),
        ),
        check_exact(
            "workflow_replay[retry_exhaustion].final_retry_allowed",
            False,
            retry_exhaustion.retry_decisions[-1].retry_allowed
            if retry_exhaustion.retry_decisions
            else None,
        ),
    ]

    return build_score(
        scorer_name="workflow_replay_scorer",
        checks=checks,
        metrics={
            "scenario_count": len(results),
            "happy_path_step_count": len(happy_path.step_executions),
            "happy_path_handoff_count": len(happy_path.handoffs),
            "retry_exhaustion_retry_count": len(retry_exhaustion.retry_decisions),
        },
    )


def build_evaluation_report(
    *,
    dataset_id: str,
    scores: Sequence[EvaluationScore],
) -> EvaluationReport:
    """Build a report and apply the initial release gates."""

    score_list = list(scores)
    release_gates = apply_initial_release_gates(score_list)
    return EvaluationReport(
        generated_at=datetime.now(UTC),
        dataset_id=dataset_id,
        passed=bool(score_list) and all(gate.passed for gate in release_gates),
        scores=score_list,
        release_gates=release_gates,
        summary={
            "score_count": len(score_list),
            "passed_score_count": sum(1 for score in score_list if score.passed),
            "release_gate_count": len(release_gates),
            "passed_release_gate_count": sum(
                1 for gate in release_gates if gate.passed
            ),
        },
    )


def apply_initial_release_gates(
    scores: Sequence[EvaluationScore],
) -> list[EvaluationReleaseGate]:
    """Evaluate the initial local release gates."""

    workflow_score = find_score(scores=scores, scorer_name="workflow_replay_scorer")
    return [
        build_release_gate(
            gate_id="workflow_replay_must_be_deterministic",
            description=(
                "All local workflow replay scenarios must pass before real AI "
                "providers are enabled."
            ),
            scorer_name="workflow_replay_scorer",
            threshold=1.0,
            score=workflow_score,
        )
    ]


def find_score(
    *,
    scores: Sequence[EvaluationScore],
    scorer_name: str,
) -> EvaluationScore | None:
    """Find a score by scorer name."""

    for score in scores:
        if score.scorer_name == scorer_name:
            return score
    return None


def build_release_gate(
    *,
    gate_id: str,
    description: str,
    scorer_name: str,
    threshold: float,
    score: EvaluationScore | None,
) -> EvaluationReleaseGate:
    """Build one release gate result."""

    actual_score = score.score if score is not None else 0.0
    return EvaluationReleaseGate(
        gate_id=gate_id,
        description=description,
        scorer_name=scorer_name,
        threshold=threshold,
        actual_score=actual_score,
        passed=score is not None and score.score >= threshold and score.passed,
    )


def render_evaluation_report(
    report: EvaluationReport,
    *,
    output_format: Literal["json", "markdown"],
) -> str:
    """Render an evaluation report in the requested output format."""

    if output_format == "json":
        return json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
    return evaluation_report_to_markdown(report)


def evaluation_report_to_markdown(report: EvaluationReport) -> str:
    """Render a human-readable Markdown evaluation report."""

    lines = [
        "# SME Back-Office Copilot Evaluation Report",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Dataset: `{report.dataset_id}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- Overall result: `{'PASS' if report.passed else 'FAIL'}`",
        "",
        "## Scores",
        "",
        "| Scorer | Score | Checks | Result |",
        "|---|---:|---:|---|",
    ]
    lines.extend(
        f"| `{score.scorer_name}` | {score.score:.2f} | "
        f"{score.passed_checks}/{score.total_checks} | "
        f"{'PASS' if score.passed else 'FAIL'} |"
        for score in report.scores
    )
    lines.extend(
        [
            "",
            "## Initial release gates",
            "",
            "| Gate | Threshold | Actual | Result |",
            "|---|---:|---:|---|",
        ]
    )
    lines.extend(
        f"| `{gate.gate_id}` | {gate.threshold:.2f} | "
        f"{gate.actual_score:.2f} | {'PASS' if gate.passed else 'FAIL'} |"
        for gate in report.release_gates
    )
    lines.extend(
        [
            "",
            "## Failed checks",
            "",
        ]
    )
    failed_checks = [
        (score.scorer_name, check)
        for score in report.scores
        for check in score.checks
        if not check.passed
    ]
    if not failed_checks:
        lines.append("No failed checks.")
    else:
        for scorer_name, check in failed_checks:
            lines.append(format_failed_check(scorer_name=scorer_name, check=check))
    lines.append("")
    return "\n".join(lines)


def format_failed_check(
    *,
    scorer_name: str,
    check: EvaluationCheck,
) -> str:
    """Render one failed check as a compact Markdown bullet."""

    return (
        f"- `{scorer_name}` / `{check.name}`: expected `{check.expected}`, "
        f"actual `{check.actual}`"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI parser for the local evaluation runner."""

    parser = argparse.ArgumentParser(
        description="Run deterministic local evaluations for SME Back-Office Copilot.",
    )
    parser.add_argument(
        "--dataset-id",
        default=DEFAULT_DATASET_ID,
        help="Evaluation dataset ID to include in the report metadata.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Report output format.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. Prints to stdout when omitted.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run local evaluation from the command line."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_evaluation_suite(dataset_id=cast(str, args.dataset_id)),
    )
    rendered = render_evaluation_report(
        report,
        output_format=cast(Literal["json", "markdown"], args.format),
    )
    output_path = cast(Path | None, args.output)
    if output_path is None:
        print(rendered)
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
