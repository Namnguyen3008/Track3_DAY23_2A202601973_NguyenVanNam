# LangGraph Agent Lab Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the LangGraph support-ticket lab with Gemini model rotation, correct routing, bounded retries, approval, persistence, metrics, report, and verified tests.

**Architecture:** Preserve the repository's existing node/state/routing separation. Add a lock-protected Gemini model iterator in `llm.py`, keep node functions as pure partial-state updates, wire the full `StateGraph`, and use explicit offline tests plus a separate live Gemini run.

**Tech Stack:** Python 3.11+, Pydantic 2, LangGraph, LangChain Google GenAI, pytest, Ruff, mypy, SQLite checkpointer.

**Spec:** `docs/superpowers/specs/2026-08-25-langgraph-agent-lab-design.md`

## Global Constraints

- Gemini rotation uses exactly `gemini-3.1-flash-lite` followed by `gemini-3.5-flash-lite` for each new factory call.
- `classify_node` must use structured LLM output; `answer_node` must use an LLM grounded in current state.
- No scenario IDs or sample query strings may be used as classification rules.
- All graph paths terminate at `finalize -> END` and retries are bounded by `attempt < max_attempts`.
- Risky routes always pass through approval; default mock approval stays offline-safe.
- The original intent stays in `state["route"]` even when the dead-letter node runs.
- API secrets stay in process environment only.
- Offline unit tests never call the network.

---

### Task 1: State, LLM rotation, node behavior, and pure routing

**Files:**
- Modify: `src/langgraph_agent_lab/state.py`
- Modify: `src/langgraph_agent_lab/llm.py`
- Modify: `src/langgraph_agent_lab/nodes.py`
- Modify: `src/langgraph_agent_lab/routing.py`
- Create: `tests/test_nodes.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- `get_llm(model: str | None = None, temperature: float = 0.0)` returns a configured chat model; Gemini calls rotate through the two exact model names unless `model` is explicit.
- Node functions accept `AgentState` and return partial dictionaries compatible with the reducers.
- Routing functions return registered graph node names and remain pure.

- [ ] **Step 1: Add failing state and routing tests.**

  Extend tests to assert the four new initial-state fields, route mapping, bounded retry decisions, and approval decisions.

- [ ] **Step 2: Run the focused tests and verify the expected failures.**

  Run: `pytest tests/test_state.py tests/test_routing.py -q`

  Expected: failures from missing state fields and `NotImplementedError` routing functions.

- [ ] **Step 3: Implement state fields and pure routing.**

  Add `evaluation_result`, `pending_question`, `proposed_action`, and serializable `approval` fields. Initialize them in `initial_state()`. Implement the four mapping/gate functions exactly as described in the spec.

- [ ] **Step 4: Run the focused tests and verify they pass.**

  Run: `pytest tests/test_state.py tests/test_routing.py -q`

- [ ] **Step 5: Add failing tests for Gemini rotation and offline node contracts.**

  Patch only the provider constructor and node-level `get_llm` in tests. Assert two successive Gemini factories receive `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite`; use a fake structured model and fake response to assert classification, grounded answer context, transient tool errors, evaluation, retry increment, approval, dead letter, and finalize events.

- [ ] **Step 6: Run the new tests and verify they fail for missing implementations.**

  Run: `pytest tests/test_llm.py tests/test_nodes.py -q`

- [ ] **Step 7: Implement the LLM factory and all node functions.**

  Use a lock-protected iterator for Gemini models. Define a Pydantic classification schema and call `get_llm().with_structured_output(schema).invoke(prompt)` in `classify_node`. Call `get_llm().invoke(prompt)` in `answer_node`, extracting string content from normal or block content. Keep the mock tool, evaluator, clarification, risky-action, approval, retry, dead-letter, and finalize logic serializable and non-mutating. Use `langgraph.types.interrupt()` only when `LANGGRAPH_INTERRUPT=true`.

- [ ] **Step 8: Run the focused tests and refactor only while green.**

  Run: `pytest tests/test_llm.py tests/test_nodes.py tests/test_state.py tests/test_routing.py -q`

- [ ] **Step 9: Commit the task.**

  Commit message: `feat: implement llm rotation and agent nodes`

### Task 2: Graph construction and persistence

**Files:**
- Modify: `src/langgraph_agent_lab/graph.py`
- Modify: `src/langgraph_agent_lab/persistence.py`
- Create: `tests/test_graph_structure.py`
- Create: `tests/test_persistence.py`

**Interfaces:**
- `build_graph(checkpointer: Any | None = None)` returns a compiled graph with all eleven nodes and the documented edges.
- `build_checkpointer(kind: str = "memory", database_url: str | None = None)` returns `None`, a memory saver, or a configured SQLite saver.

- [ ] **Step 1: Add failing graph and persistence tests.**

  Assert the compiled graph contains `intake`, `classify`, `tool`, `evaluate`, `answer`, `clarify`, `risky_action`, `approval`, `retry`, `dead_letter`, and `finalize`. Invoke with a deterministic fake-node graph only if necessary to inspect termination. Assert SQLite creates a checkpointer and rejects unknown kinds.

- [ ] **Step 2: Run the focused tests and verify the expected failures.**

  Run: `pytest tests/test_graph_structure.py tests/test_persistence.py -q`

  Expected: `build_graph()` and SQLite currently raise `NotImplementedError`.

- [ ] **Step 3: Implement graph wiring and SQLite support.**

  Register all nodes, add `START -> intake -> classify`, conditional classify/evaluate/retry/approval edges, fixed edges to `finalize`, and `finalize -> END`. For SQLite use `sqlite3.connect(path, check_same_thread=False)`, WAL mode, `SqliteSaver(conn)`, and `setup()`.

- [ ] **Step 4: Run focused and existing graph tests.**

  Run: `pytest tests/test_graph_structure.py tests/test_persistence.py tests/test_state.py tests/test_routing.py -q`

- [ ] **Step 5: Commit the task.**

  Commit message: `feat: wire langgraph workflow and sqlite checkpoints`

### Task 3: Metrics, report, and execution evidence

**Files:**
- Modify: `src/langgraph_agent_lab/metrics.py`
- Modify: `src/langgraph_agent_lab/cli.py`
- Modify: `src/langgraph_agent_lab/report.py`
- Create: `tests/test_report.py`
- Create: `configs/lab_sqlite.yaml`
- Create: `reports/lab_report.md`

**Interfaces:**
- `summarize_metrics(items, resume_success=False)` returns a validated `MetricsReport`.
- `render_report(metrics: MetricsReport)` returns complete Markdown without secrets.
- CLI scenario execution continues to write `outputs/metrics.json` and the configured report.

- [ ] **Step 1: Add failing report/metrics tests.**

  Assert the report contains summary values, every scenario row, architecture/state sections, failure analysis, persistence evidence, and improvement plan. Assert `resume_success` can be propagated without changing existing metric callers.

- [ ] **Step 2: Run the focused tests and verify they fail.**

  Run: `pytest tests/test_report.py tests/test_metrics.py -q`

- [ ] **Step 3: Implement metrics propagation, report rendering, and SQLite config.**

  Preserve the existing Pydantic schema and metric calculations. Render Markdown from the metric object, escape table cells, and never include environment values. Add a SQLite config for explicit persistence evidence while leaving the memory config usable for offline tests.

- [ ] **Step 4: Run focused tests and local validation.**

  Run: `pytest tests/test_report.py tests/test_metrics.py -q`; then `python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json` after a scenario run.

- [ ] **Step 5: Commit the task.**

  Commit message: `feat: add metrics report and persistence run config`

### Task 4: Full verification and live Gemini scenarios

**Files:**
- Modify: `reports/lab_report.md` with generated evidence only
- Generate: `outputs/metrics.json`
- Generate: `reports/lab_report.md`

- [ ] **Step 1: Create the project virtual environment and install project extras.**

  On Windows run: `python -m venv .venv`; then `.venv\\Scripts\\python.exe -m pip install -e ".[dev,google,sqlite]"`.

- [ ] **Step 2: Run the complete offline suite and quality checks.**

  Run: `.venv\\Scripts\\python.exe -m pytest -q`; `.venv\\Scripts\\ruff.exe check src tests`; `.venv\\Scripts\\mypy.exe src`.

- [ ] **Step 3: Run the live Gemini smoke/scenario commands with the process key.**

  Set `GEMINI_API_KEY` only in the current PowerShell process. Run the graph smoke test and `.venv\\Scripts\\python.exe -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json`. Verify the rotation test has observed both model names without printing the key.

- [ ] **Step 4: Validate metrics and report.**

  Run: `.venv\\Scripts\\python.exe -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json`. Inspect the JSON/report for seven scenarios, correct routes, retry counts, approval observations, and no secret strings.

- [ ] **Step 5: Review the final diff and commit verification artifacts.**

  Run: `git diff --check`; `git status --short`; `rg -n "TODO\\(student\\)|NotImplementedError|AQ\\.|AIza|sk-" src tests reports configs`. Commit generated assignment artifacts only after the checks show no key material.

---
