import json

from app.evaluations import EvaluationScore
from app.evaluations.runner import (
    build_evaluation_report,
    evaluation_report_to_markdown,
    main,
    render_evaluation_report,
    run_evaluation_suite,
    score_workflow_replay,
)


async def test_workflow_replay_evaluation_scores_all_scenarios() -> None:
    score = await score_workflow_replay()

    assert score.scorer_name == "workflow_replay_scorer"
    assert score.passed is True
    assert score.score == 1.0
    assert score.metrics["scenario_count"] == 3
    assert score.metrics["happy_path_step_count"] == 12


async def test_evaluation_suite_builds_passing_report() -> None:
    report = await run_evaluation_suite()

    assert report.schema_version == "evaluation.report.v1"
    assert report.dataset_id == "sme_local_v1"
    assert report.passed is True
    assert len(report.scores) == 1
    assert report.release_gates[0].gate_id == "workflow_replay_must_be_deterministic"
    assert report.release_gates[0].passed is True


def test_evaluation_report_marks_failed_release_gate() -> None:
    failing_score = EvaluationScore(
        scorer_name="workflow_replay_scorer",
        score=0.5,
        passed=False,
        passed_checks=1,
        total_checks=2,
    )

    report = build_evaluation_report(
        dataset_id="sme_local_v1",
        scores=[failing_score],
    )

    assert report.passed is False
    assert report.release_gates[0].passed is False
    assert report.release_gates[0].actual_score == 0.5


def test_evaluation_report_renders_markdown() -> None:
    passing_score = EvaluationScore(
        scorer_name="workflow_replay_scorer",
        score=1.0,
        passed=True,
        passed_checks=2,
        total_checks=2,
    )
    report = build_evaluation_report(
        dataset_id="sme_local_v1",
        scores=[passing_score],
    )

    markdown = evaluation_report_to_markdown(report)

    assert "# SME Back-Office Copilot Evaluation Report" in markdown
    assert "workflow_replay_must_be_deterministic" in markdown
    assert "No failed checks." in markdown


async def test_evaluation_report_renders_json() -> None:
    report = await run_evaluation_suite()

    payload = json.loads(render_evaluation_report(report, output_format="json"))

    assert payload["passed"] is True
    assert payload["scores"][0]["scorer_name"] == "workflow_replay_scorer"


def test_evaluation_command_writes_json_report(tmp_path) -> None:
    output_path = tmp_path / "evaluation-report.json"

    exit_code = main(
        [
            "--format",
            "json",
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["release_gates"][0]["passed"] is True
