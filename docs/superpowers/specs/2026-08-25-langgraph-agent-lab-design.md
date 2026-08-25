# LangGraph Agent Lab Completion Design

## Goal

Complete the Day 08/Day 23 LangGraph support-ticket lab in the existing repository so the graph executes every sample and hidden route, uses real Gemini structured-output and grounded-generation calls, records metrics, supports checkpoint persistence, and produces a usable report.

## Scope

The implementation covers the intentionally empty production functions in `src/langgraph_agent_lab/`, the missing unit/integration coverage needed to protect their behavior, and the report/configuration artifacts required by the repository rubric. It does not add a web UI, external support-ticket service, or unrelated refactor.

## Binding requirements

- Python version remains `>=3.11` and the existing `pyproject.toml` package layout is preserved.
- When `GEMINI_API_KEY` is available, the Gemini models rotate in this exact order: `gemini-3.1-flash-lite`, then `gemini-3.5-flash-lite`, repeating for each new LLM factory call.
- `classify_node` uses `with_structured_output()` and classifies only `simple`, `tool`, `missing_info`, `risky`, or `error`.
- `answer_node` uses a real LLM call and grounds the response in the query, tool results, proposed action, and approval state.
- No node may classify or answer by matching scenario IDs or the seven sample query strings.
- Retry is bounded by `attempt < max_attempts`; every route reaches `finalize` and then `END`.
- Risky actions pass through an approval node. Mock approval is the default for CI; `LANGGRAPH_INTERRUPT=true` enables a real LangGraph interrupt/resume path.
- `route` remains the intent route (`error` for the dead-letter sample); `dead_letter` is a graph node, not a replacement intent.
- State remains JSON/checkpointer serializable. Append-only lists use the existing `operator.add` reducers; scalar fields overwrite.
- The API key is consumed from the process environment for tests and runs and is never written to source, generated reports, or commits.
- Offline unit tests must not make network calls. Gemini integration/scenario runs are explicit commands and require `GEMINI_API_KEY`.

## Architecture

The workflow is:

```text
START -> intake -> classify
  simple       -> answer -> finalize -> END
  tool         -> tool -> evaluate -> answer/fail-retry loop
  missing_info -> clarify -> finalize -> END
  risky        -> risky_action -> approval -> tool -> evaluate -> ...
  error        -> retry -> bounded tool/evaluate loop -> dead_letter or answer
```

`llm.py` owns provider construction and Gemini model rotation. `nodes.py` owns state transitions and audit events. `routing.py` contains pure conditional-edge decisions. `graph.py` only wires nodes and edges. `persistence.py` owns checkpointer construction. `metrics.py`, `cli.py`, and `report.py` own execution evidence and presentation.

## State design

Existing `messages`, `tool_results`, `errors`, and `events` remain append-only. Add these overwrite fields:

| Field | Type | Purpose |
|---|---|---|
| `evaluation_result` | `str` | Gate after tool evaluation: `success` or `needs_retry` |
| `pending_question` | `str | None` | Clarification question shown to the user |
| `proposed_action` | `str | None` | Risky action awaiting approval |
| `approval` | `dict[str, Any] | None` | Serializable approval decision |

`initial_state()` initializes every field so every route can be checkpointed from its first step.

## LLM behavior

`get_llm()` keeps the existing OpenAI/Anthropic fallback behavior, but Gemini takes precedence when `GEMINI_API_KEY` is set. A lock-protected iterator selects the next Gemini model per factory call. An explicit `model=` argument is respected for deterministic tests or debugging; otherwise the two-model rotation is used.

The classification prompt explicitly states priority `risky > tool > missing_info > error > simple`, asks for a Pydantic schema, and includes no scenario-specific matching. The answer prompt includes only the original query and serialized current context, instructing the model not to invent tool facts.

## Failure and recovery behavior

- `tool_node` simulates transient `ERROR` results for the error route while `attempt < 2`; later attempts succeed.
- `evaluate_node` turns the latest tool result into `needs_retry` or `success`.
- `retry_or_fallback_node` increments the attempt and appends an error event.
- `dead_letter_node` creates a deterministic escalation answer after the configured limit.
- The default approval decision is approved for offline scenario execution. The interrupt mode emits a JSON-serializable payload and resumes using the same `thread_id`.
- SQLite uses a file connection with `check_same_thread=False`, WAL mode, and the installed `SqliteSaver` package. Memory remains the default test checkpointer.

## Metrics and report

`metrics.json` remains validated by the existing Pydantic models. `summarize_metrics()` accepts an optional recovery result while preserving existing callers. The scenario runner records route correctness, retry count, approval observation, errors, and node count. The report renderer produces a summary table, per-scenario table, architecture/state explanation, failure analysis, persistence evidence, and improvements.

## Verification

The implementation is accepted only after:

1. focused unit tests are written and observed failing before each behavior is implemented;
2. the full offline pytest suite passes;
3. `ruff check src tests` and `mypy src` are run and their actual output is reviewed;
4. the Gemini integration smoke test and sample scenario runner complete with the supplied environment key;
5. `outputs/metrics.json` passes `validate-metrics` and the report contains the generated evidence;
6. the final diff contains no API key or unimplemented TODO marker in executable code.
