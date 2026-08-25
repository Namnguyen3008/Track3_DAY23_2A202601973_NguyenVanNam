"""Report generation helper."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def _escape_cell(value: object) -> str:
    """Escape a value for a Markdown table cell without reading environment data."""
    if value is None:
        return "—"
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>")
    return text or "—"


def _summary_table(metrics: MetricsReport) -> list[str]:
    resume_value = str(metrics.resume_success).lower()
    rows = [
        ("Total scenarios", metrics.total_scenarios),
        ("Success rate", f"{metrics.success_rate:.2%}"),
        ("Average nodes visited", f"{metrics.avg_nodes_visited:.2f}"),
        ("Total retries", metrics.total_retries),
        ("Total interrupts", metrics.total_interrupts),
        ("Resume success", resume_value),
    ]
    return [
        "| Metric | Value |",
        "|---|---:|",
        *[
            f"| {_escape_cell(label)} | {_escape_cell(value)} |"
            for label, value in rows
        ],
    ]


def _scenario_table(metrics: MetricsReport) -> list[str]:
    lines = [
        (
            "| Scenario | Expected route | Actual route | Success | Nodes | Retries | "
            "Interrupts | Errors |"
        ),
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in metrics.scenario_metrics:
        errors = "; ".join(item.errors) if item.errors else "—"
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_cell(item.scenario_id),
                    _escape_cell(item.expected_route),
                    _escape_cell(item.actual_route),
                    _escape_cell("Yes" if item.success else "No"),
                    _escape_cell(item.nodes_visited),
                    _escape_cell(item.retry_count),
                    _escape_cell(item.interrupt_count),
                    _escape_cell(errors),
                ]
            )
            + " |"
        )
    return lines


def render_report(metrics: MetricsReport) -> str:
    """Render a complete, deterministic Markdown report from validated metrics."""
    resume_value = str(metrics.resume_success).lower()
    lines = [
        "# Day 08 Lab Report",
        "",
        "## 1. Team / student",
        "",
        "- Name: Nguyễn Văn Nam",
        "- Student ID: 2A202601973",
        "- Repo/commit: Not provided",
        "- Date: Not provided",
        "",
        "## Summary",
        "",
        (
            "This report is rendered from the validated `MetricsReport` object. "
            "It contains no environment values or secrets."
        ),
        "",
        *_summary_table(metrics),
        "",
        "## 2. Architecture",
        "",
        (
            "The workflow is a compiled LangGraph state machine: "
            "`START -> intake -> classify`, followed by a conditional route."
        ),
        (
            "Simple requests go to `answer`; tool requests go through "
            "`tool -> evaluate`; missing information goes to `clarify`; risky actions "
            "go through `risky_action -> approval`; and error routes enter the bounded "
            "retry loop."
        ),
        (
            "Every terminal branch reaches `finalize -> END`. The nodes return partial "
            "state updates, while `routing.py` contains pure conditional-edge decisions."
        ),
        "",
        "## 3. State schema",
        "",
        (
            "Append-only collections use the existing `operator.add` reducer so each "
            "node contributes only its new entries. Scalar fields are overwritten by "
            "the latest node update."
        ),
        "",
        "| Field | Reducer | Purpose |",
        "|---|---|---|",
        "| messages | append | Preserve the conversation/audit trail. |",
        "| tool_results | append | Keep tool outputs across retries. |",
        "| errors | append | Preserve retry and failure evidence. |",
        "| events | append | Record node visits and normalized audit events. |",
        (
            "| route, risk_level, attempt, max_attempts | overwrite | "
            "Track current routing and retry state. |"
        ),
        (
            "| final_answer, pending_question, proposed_action, approval | overwrite | "
            "Store the current user-facing or approval state. |"
        ),
        (
            "| thread_id, scenario_id, query, evaluation_result | overwrite | "
            "Identify the run and current evaluation context. |"
        ),
        "",
        "## 4. Scenario results",
        "",
        *_scenario_table(metrics),
        "",
        "## 5. Failure analysis",
        "",
        (
            "1. **Transient tool failure:** `evaluate` marks an `ERROR` result as "
            "`needs_retry`; `retry` increments the attempt and routes back to `tool` "
            "only while `attempt < max_attempts`. Exhausted attempts go to "
            "`dead_letter` and still finalize."
        ),
        (
            "2. **Risky action without approval:** sensitive work is prepared by "
            "`risky_action` and must pass through `approval`. A rejection routes to "
            "`clarify`, so the action is not executed without a recorded decision."
        ),
        (
            "3. **Route or output mismatch:** the per-scenario metric compares the "
            "actual route and required output/approval observation with the expected "
            "scenario contract, making a silent wrong branch visible."
        ),
        "",
        "## 6. Persistence / recovery evidence",
        "",
        (
            "The CLI assigns each scenario a stable `thread_id` and builds either the "
            "default in-memory checkpointer or the SQLite checkpointer selected by "
            "configuration. The SQLite run configuration is provided in "
            "`configs/lab_sqlite.yaml`."
        ),
        (
            f"The metrics object records `resume_success={resume_value}`. This flag is "
            "reserved for verified crash-resume or state-history replay. Ordinary "
            "checkpoint history after a completed invocation is not recovery evidence; "
            "the normal CLI scenario path leaves the value false because it does not "
            "perform replay."
        ),
        "",
        "## 7. Extension work",
        "",
        (
            "SQLite persistence is available as an explicit run configuration, with "
            "WAL mode and thread-safe connections supplied by the existing checkpointer "
            "adapter. The generated report also exposes retry, approval, and node-visit "
            "evidence for later tracing or time-travel extensions."
        ),
        "",
        "## 8. Improvement plan",
        "",
        (
            "- Add an automated crash-and-resume integration test that kills and restarts "
            "a SQLite-backed process, then verifies the same thread resumes from its "
            "checkpoint."
        ),
        (
            "- Add latency instrumentation around each node and export route-level "
            "percentiles alongside the current averages."
        ),
        (
            "- Replace the mock approval path with an authenticated reviewer workflow "
            "and retain the approval audit event in a durable store."
        ),
        "",
    ]
    return "\n".join(lines)


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    """Write the rendered report to a file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(metrics), encoding="utf-8")
