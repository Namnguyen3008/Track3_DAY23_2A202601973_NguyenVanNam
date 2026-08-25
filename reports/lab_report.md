# Day 08 Lab Report

## 1. Team / student

- Name: Not provided
- Repo/commit: Not provided
- Date: Not provided

## Summary

This report is rendered from the validated `MetricsReport` object. It contains no environment values or secrets.

| Metric | Value |
|---|---:|
| Total scenarios | 7 |
| Success rate | 100.00% |
| Average nodes visited | 6.43 |
| Total retries | 3 |
| Total interrupts | 2 |
| Resume success | false |

## 2. Architecture

The workflow is a compiled LangGraph state machine: `START -> intake -> classify`, followed by a conditional route.
Simple requests go to `answer`; tool requests go through `tool -> evaluate`; missing information goes to `clarify`; risky actions go through `risky_action -> approval`; and error routes enter the bounded retry loop.
Every terminal branch reaches `finalize -> END`. The nodes return partial state updates, while `routing.py` contains pure conditional-edge decisions.

## 3. State schema

Append-only collections use the existing `operator.add` reducer so each node contributes only its new entries. Scalar fields are overwritten by the latest node update.

| Field | Reducer | Purpose |
|---|---|---|
| messages | append | Preserve the conversation/audit trail. |
| tool_results | append | Keep tool outputs across retries. |
| errors | append | Preserve retry and failure evidence. |
| events | append | Record node visits and normalized audit events. |
| route, risk_level, attempt, max_attempts | overwrite | Track current routing and retry state. |
| final_answer, pending_question, proposed_action, approval | overwrite | Store the current user-facing or approval state. |
| thread_id, scenario_id, query, evaluation_result | overwrite | Identify the run and current evaluation context. |

## 4. Scenario results

| Scenario | Expected route | Actual route | Success | Nodes | Retries | Interrupts | Errors |
|---|---|---|---:|---:|---:|---:|---|
| S01_simple | simple | simple | Yes | 4 | 0 | 0 | — |
| S02_tool | tool | tool | Yes | 6 | 0 | 0 | — |
| S03_missing | missing_info | missing_info | Yes | 4 | 0 | 0 | — |
| S04_risky | risky | risky | Yes | 8 | 0 | 1 | — |
| S05_error | error | error | Yes | 10 | 2 | 0 | retry attempt 1: transient tool failure; retry attempt 2: transient tool failure |
| S06_delete | risky | risky | Yes | 8 | 0 | 1 | — |
| S07_dead_letter | error | error | Yes | 5 | 1 | 0 | retry attempt 1: transient tool failure |

## 5. Failure analysis

1. **Transient tool failure:** `evaluate` marks an `ERROR` result as `needs_retry`; `retry` increments the attempt and routes back to `tool` only while `attempt < max_attempts`. Exhausted attempts go to `dead_letter` and still finalize.
2. **Risky action without approval:** sensitive work is prepared by `risky_action` and must pass through `approval`. A rejection routes to `clarify`, so the action is not executed without a recorded decision.
3. **Route or output mismatch:** the per-scenario metric compares the actual route and required output/approval observation with the expected scenario contract, making a silent wrong branch visible.

## 6. Persistence / recovery evidence

The CLI assigns each scenario a stable `thread_id` and builds either the default in-memory checkpointer or the SQLite checkpointer selected by configuration. The SQLite run configuration is provided in `configs/lab_sqlite.yaml`.
The metrics object records `resume_success=false`. This flag is reserved for verified crash-resume or state-history replay. Ordinary checkpoint history after a completed invocation is not recovery evidence; the normal CLI scenario path leaves the value false because it does not perform replay.

## 7. Extension work

SQLite persistence is available as an explicit run configuration, with WAL mode and thread-safe connections supplied by the existing checkpointer adapter. The generated report also exposes retry, approval, and node-visit evidence for later tracing or time-travel extensions.

## 8. Improvement plan

- Add an automated crash-and-resume integration test that kills and restarts a SQLite-backed process, then verifies the same thread resumes from its checkpoint.
- Add latency instrumentation around each node and export route-level percentiles alongside the current averages.
- Replace the mock approval path with an authenticated reviewer workflow and retain the approval audit event in a durable store.
