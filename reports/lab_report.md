# Day 08 Lab Report

> This checked-in artifact is a deterministic offline contract fixture for the report renderer. It documents the seven sample scenario rows and report shape without invoking Gemini. A scenario run replaces it with execution metrics.

## 1. Team / student

- Name: Not provided
- Repo/commit: Not provided
- Date: Not provided

## Summary

| Metric | Value |
|---|---:|
| Total scenarios | 7 |
| Success rate | 100.00% |
| Average nodes visited | 6.43 |
| Total retries | 3 |
| Total interrupts | 2 |
| Resume success | false |

The values above represent the expected route/flow contract used for the offline report artifact; no environment values or secrets are included.

## 2. Architecture

The workflow is a compiled LangGraph state machine:

`START -> intake -> classify -> conditional route`

- `simple -> answer -> finalize -> END`
- `tool -> evaluate -> answer` or the bounded retry loop
- `missing_info -> clarify -> finalize -> END`
- `risky -> risky_action -> approval -> tool -> evaluate`
- `error -> retry -> tool/evaluate` or `dead_letter -> finalize -> END`

Nodes return partial state updates. Pure functions in `routing.py` select conditional edges, and `finalize` is the common terminal audit step.

## 3. State schema

Append-only collections use the existing `operator.add` reducer. Scalar fields are overwritten by the latest node update.

| Field | Reducer | Why |
|---|---|---|
| `messages` | append | Preserve conversation/audit messages. |
| `tool_results` | append | Keep tool outputs across retries. |
| `errors` | append | Preserve retry and failure evidence. |
| `events` | append | Record normalized node visits. |
| `route`, `risk_level`, `attempt`, `max_attempts` | overwrite | Track the current route and retry gate. |
| `final_answer`, `pending_question`, `proposed_action`, `approval` | overwrite | Store current user-facing and approval state. |
| `thread_id`, `scenario_id`, `query`, `evaluation_result` | overwrite | Identify the run and current evaluation context. |

## 4. Scenario results

| Scenario | Expected route | Actual route | Success | Nodes | Retries | Interrupts | Errors |
|---|---|---|---:|---:|---:|---:|---|
| S01_simple | simple | simple | Yes | 4 | 0 | 0 | — |
| S02_tool | tool | tool | Yes | 6 | 0 | 0 | — |
| S03_missing | missing_info | missing_info | Yes | 4 | 0 | 0 | — |
| S04_risky | risky | risky | Yes | 8 | 0 | 1 | — |
| S05_error | error | error | Yes | 10 | 2 | 0 | — |
| S06_delete | risky | risky | Yes | 8 | 0 | 1 | — |
| S07_dead_letter | error | error | Yes | 5 | 1 | 0 | — |

## 5. Failure analysis

1. **Transient tool failure:** `evaluate` marks an `ERROR` result as `needs_retry`; `retry` increments the attempt and routes back to `tool` only while `attempt < max_attempts`. Exhausted attempts go to `dead_letter` and still finalize.
2. **Risky action without approval:** sensitive work is prepared by `risky_action` and must pass through `approval`. A rejection routes to `clarify`, so the action is not executed without a recorded decision.
3. **Route or output mismatch:** metrics compare the actual route and required output/approval observation with the expected scenario contract, making a wrong branch visible.

## 6. Persistence / recovery evidence

Each scenario receives a stable `thread_id`, and the CLI selects the default memory checkpointer or the SQLite checkpointer from configuration. `configs/lab_sqlite.yaml` provides the explicit SQLite run configuration.

The checked-in fixture records `resume_success=false` because no live replay or crash-resume run was performed during offline verification. Ordinary checkpoint history after a completed invocation is not recovery evidence. The SQLite adapter uses WAL mode and thread-safe connections; the focused persistence tests verify database setup and cross-thread access.

## 7. Extension work

SQLite persistence is available as an explicit configuration extension. The metrics/report path also preserves retry counts, approval observations, node visits, and errors for future tracing or time-travel work.

## 8. Improvement plan

- Add an automated crash-and-resume integration test that restarts a SQLite-backed process and verifies the same thread resumes from its checkpoint.
- Add per-node latency instrumentation and route-level percentile reporting.
- Replace mock approval with an authenticated reviewer workflow and retain the approval audit event durably.
