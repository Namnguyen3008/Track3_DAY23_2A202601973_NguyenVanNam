# Task 1 Implementation Report

## Scope

Implemented Task 1 only: state fields, pure routing, Gemini model rotation, LLM-backed node behavior, offline-safe approval, bounded retry/dead-letter behavior, and focused offline tests.

## Changed files

- `src/langgraph_agent_lab/state.py`
  - Added `evaluation_result`, `pending_question`, `proposed_action`, and serializable `approval` fields to `AgentState`.
  - Initialized all four fields in `initial_state()`.
- `src/langgraph_agent_lab/llm.py`
  - Added a lock-protected Gemini rotation using exactly `gemini-3.1-flash-lite` followed by `gemini-3.5-flash-lite`.
  - Preserved explicit model selection and OpenAI/Anthropic fallback behavior.
- `src/langgraph_agent_lab/nodes.py`
  - Added the Pydantic structured classification schema and LLM-backed classification.
  - Added grounded LLM answer generation with normal and block-content extraction.
  - Implemented mock tool errors, evaluation, clarification, risky-action preparation, approval/interrupt opt-in, retry tracking, dead-letter handling, and finalize events.
  - Kept node functions non-mutating and reducer-compatible.
- `src/langgraph_agent_lab/routing.py`
  - Implemented pure classify, evaluate, retry-limit, and approval route decisions.
- `tests/test_llm.py`
  - Added offline constructor tests for exact Gemini rotation and explicit-model bypass.
- `tests/test_nodes.py`
  - Added offline tests for initial state fields and all Task 1 node contracts using fakes only.

No graph, persistence, metrics, CLI, report, config, or unrelated files were modified. No API key was written to any file.

## TDD evidence

1. `pytest tests/test_state.py tests/test_routing.py -q` — red as expected: 13 routing failures from the unimplemented routing functions; 3 existing state tests passed.
2. `pytest tests/test_llm.py tests/test_nodes.py -q` — red as expected: the Gemini default was still the old model and node implementations raised `NotImplementedError`.
3. `pytest tests/test_nodes.py::test_initial_state_has_serializable_workflow_fields -q` — red as expected with `KeyError: 'evaluation_result'`.
4. After the minimal state/routing implementation, `pytest tests/test_state.py tests/test_routing.py tests/test_nodes.py::test_initial_state_has_serializable_workflow_fields -q` — `17 passed`.
5. Final focused run: `pytest tests/test_llm.py tests/test_nodes.py tests/test_state.py tests/test_routing.py` — `30 passed in 0.22s`.

## Additional verification

- `$env:GEMINI_API_KEY = $null; $env:OPENAI_API_KEY = $null; $env:ANTHROPIC_API_KEY = $null; pytest -ra` — `33 passed, 6 skipped`; all six skipped tests are API-dependent graph smoke tests.
- `git diff --check` — passed.
- The focused tests patch the provider constructor or node-level `get_llm`; no test made a network request.

## Self-review

- Gemini rotation advances only for implicit Gemini factory calls and is protected by a process-local lock.
- Classification uses `with_structured_output(Classification)` and does not use scenario IDs or sample-query matching.
- Answer prompts include the original query, tool results, proposed action, and approval state.
- Partial node updates do not mutate their input state. Approval remains a plain JSON-serializable dictionary.
- Retry routing is bounded by `attempt < max_attempts`; dead-letter output does not overwrite the original `route`.
- All emitted events use the existing normalized `make_event()` shape.

## Concerns

- Per instruction, no live Gemini/API validation was run. The full offline suite therefore skips the existing graph smoke tests.
- `graph.py` and `persistence.py` remain intentionally unimplemented because they belong to later tasks and were outside the permitted scope.
- A source-only `mypy` command was stopped after hanging in the local environment; the repository’s configured Ruff check also reports existing annotation/style findings outside the focused functional tests.
