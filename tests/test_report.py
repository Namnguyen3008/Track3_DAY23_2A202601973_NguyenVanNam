from pathlib import Path

import pytest

from langgraph_agent_lab.metrics import ScenarioMetric, summarize_metrics
from langgraph_agent_lab.report import render_report, write_report


def _scenario_metrics() -> list[ScenarioMetric]:
    return [
        ScenarioMetric(
            scenario_id="S01_simple",
            success=True,
            expected_route="simple",
            actual_route="simple",
            nodes_visited=3,
        ),
        ScenarioMetric(
            scenario_id="S|02_tool",
            success=False,
            expected_route="risky",
            actual_route="tool",
            nodes_visited=4,
            retry_count=2,
            interrupt_count=1,
            approval_required=True,
            approval_observed=False,
            errors=["timeout | retry"],
        ),
    ]


def test_summarize_metrics_propagates_recovery_result_without_changing_callers() -> None:
    metrics = _scenario_metrics()

    recovered = summarize_metrics(metrics, resume_success=True)
    default = summarize_metrics(metrics)

    assert recovered.resume_success is True
    assert default.resume_success is False
    assert recovered.total_scenarios == 2
    assert recovered.total_retries == 2
    assert recovered.total_interrupts == 1


def test_render_report_contains_complete_metrics_and_evidence() -> None:
    report = render_report(summarize_metrics(_scenario_metrics(), resume_success=True))

    assert "## 1. Team / student" in report
    assert "- Name: Not provided" in report
    assert "- Repo/commit: Not provided" in report
    assert "- Date: Not provided" in report
    assert "Total scenarios" in report
    assert "2" in report
    assert "50.00%" in report
    assert "Average nodes visited" in report
    assert "3.50" in report
    assert "Total retries" in report
    assert "Total interrupts" in report
    assert "| S01_simple |" in report
    assert "| S\\|02_tool |" in report
    assert "timeout \\| retry" in report
    assert "## 2. Architecture" in report
    assert "## 3. State schema" in report
    assert "## 4. Scenario results" in report
    assert "## 5. Failure analysis" in report
    assert "## 6. Persistence / recovery evidence" in report
    assert "## 8. Improvement plan" in report
    assert "resume_success=true" in report
    assert (
        "Ordinary checkpoint history after a completed invocation is not recovery evidence"
        in report
    )


def test_render_report_does_not_read_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "offline-env-marker-value"
    monkeypatch.setenv("LANGGRAPH_REPORT_MARKER", marker)

    report = render_report(summarize_metrics(_scenario_metrics()))

    assert marker not in report
    assert "LANGGRAPH_REPORT_MARKER" not in report


def test_render_report_escapes_newlines_backslashes_and_none_cells() -> None:
    metric = ScenarioMetric(
        scenario_id="S\\03\nnewline",
        success=False,
        expected_route="expected|route\\",
        actual_route=None,
        errors=["first\nsecond", "slash\\pipe|"],
    )

    report = render_report(summarize_metrics([metric]))

    assert "| S\\\\03<br>newline |" in report
    assert "| expected\\|route\\\\ |" in report
    assert "| — |" in report
    assert "first<br>second; slash\\\\pipe\\|" in report


def test_write_report_writes_the_complete_rendered_document(tmp_path: Path) -> None:
    metrics = summarize_metrics(_scenario_metrics())
    expected = render_report(metrics)
    output_path = tmp_path / "nested" / "report.md"

    write_report(metrics, output_path)

    contents = output_path.read_text(encoding="utf-8")
    assert contents == expected
    assert contents.startswith("# Day 08 Lab Report\n")
    assert contents.endswith("\n")
