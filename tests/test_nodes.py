from types import SimpleNamespace

from langgraph_agent_lab import nodes
from langgraph_agent_lab.state import Route, Scenario, initial_state


class FakeStructuredModel:
    def __init__(self, response):
        self.response = response
        self.prompts = []
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.response


class FakeTextModel:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.response


def event_types(result):
    return [event["event_type"] for event in result["events"]]


def test_initial_state_has_serializable_workflow_fields():
    state = initial_state(Scenario(id="state", query="hello", expected_route=Route.SIMPLE))

    assert state["evaluation_result"] == ""
    assert state["pending_question"] is None
    assert state["proposed_action"] is None
    assert state["approval"] is None


def test_classify_node_uses_structured_output_and_returns_route(monkeypatch):
    model = FakeStructuredModel(SimpleNamespace(route="tool", risk_level="low"))
    monkeypatch.setattr(nodes, "get_llm", lambda: model)
    state = {"query": "Please look up order 12345", "route": ""}

    result = nodes.classify_node(state)

    assert result["route"] == "tool"
    assert result["risk_level"] == "low"
    assert model.schema is not None
    assert "Please look up order 12345" in model.prompts[0]
    assert event_types(result) == ["completed"]
    assert state == {"query": "Please look up order 12345", "route": ""}


def test_classification_prompt_disambiguates_instructions_from_lookups(monkeypatch):
    model = FakeStructuredModel(SimpleNamespace(route="simple", risk_level="low"))
    monkeypatch.setattr(nodes, "get_llm", lambda: model)

    nodes.classify_node({"query": "How do I change a setting?"})

    prompt = model.prompts[0].casefold()
    assert "instructions or explanations" in prompt
    assert "current record" in prompt
    assert "must never be tool" in prompt


def test_answer_node_grounds_llm_prompt_in_current_state(monkeypatch):
    model = FakeTextModel(SimpleNamespace(content="The order is shipped."))
    monkeypatch.setattr(nodes, "get_llm", lambda: model)
    state = {
        "query": "Where is order 12345?",
        "tool_results": ["order 12345: shipped"],
        "proposed_action": "",
        "approval": {"approved": True, "reviewer": "mock-reviewer", "comment": ""},
    }

    result = nodes.answer_node(state)

    assert result["final_answer"] == "The order is shipped."
    prompt = model.prompts[0]
    assert "Where is order 12345?" in prompt
    assert "order 12345: shipped" in prompt
    assert "approved" in prompt
    assert event_types(result) == ["completed"]


def test_answer_node_extracts_text_from_block_content(monkeypatch):
    model = FakeTextModel(
        SimpleNamespace(content=[{"type": "text", "text": "Block answer"}])
    )
    monkeypatch.setattr(nodes, "get_llm", lambda: model)

    result = nodes.answer_node({"query": "Explain the status"})

    assert result["final_answer"] == "Block answer"


def test_tool_node_returns_transient_error_then_success():
    first = nodes.tool_node({"route": "error", "attempt": 0, "query": "retry this"})
    later = nodes.tool_node({"route": "error", "attempt": 2, "query": "retry this"})

    assert "ERROR" in first["tool_results"][0]
    assert "ERROR" not in later["tool_results"][0]
    assert len(first["events"]) == 1
    assert len(later["events"]) == 1


def test_evaluate_node_marks_error_result_for_retry():
    result = nodes.evaluate_node({"tool_results": ["ERROR: transient mock failure"]})

    assert result["evaluation_result"] == "needs_retry"
    assert event_types(result) == ["completed"]


def test_retry_node_increments_attempt_without_mutating_state():
    state = {"attempt": 1, "errors": ["old error"]}

    result = nodes.retry_or_fallback_node(state)

    assert result["attempt"] == 2
    assert len(result["errors"]) == 1
    assert "retry" in result["errors"][0].lower()
    assert state == {"attempt": 1, "errors": ["old error"]}


def test_clarification_node_sets_question_and_answer():
    result = nodes.ask_clarification_node({"query": "Can you fix it?"})

    assert result["pending_question"]
    assert result["final_answer"] == result["pending_question"]
    assert event_types(result) == ["completed"]


def test_risky_action_node_proposes_action():
    result = nodes.risky_action_node({"query": "Refund the customer"})

    assert "Refund the customer" in result["proposed_action"]
    assert event_types(result) == ["completed"]


def test_approval_node_defaults_to_serializable_mock_approval(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_INTERRUPT", raising=False)

    result = nodes.approval_node({"proposed_action": "Refund the customer"})

    assert result["approval"] == {
        "approved": True,
        "reviewer": "mock-reviewer",
        "comment": "mock approval",
    }
    assert event_types(result) == ["completed"]


def test_approval_node_uses_interrupt_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_INTERRUPT", "true")
    monkeypatch.setattr(
        "langgraph.types.interrupt",
        lambda payload: {
            "approved": False,
            "reviewer": "human-reviewer",
            "comment": "needs more evidence",
        },
    )

    result = nodes.approval_node({"query": "delete account", "proposed_action": "delete"})

    assert result["approval"] == {
        "approved": False,
        "reviewer": "human-reviewer",
        "comment": "needs more evidence",
    }


def test_dead_letter_node_keeps_route_in_input_and_explains_failure():
    state = {
        "route": "error",
        "query": "System failure",
        "attempt": 1,
        "max_attempts": 1,
    }

    result = nodes.dead_letter_node(state)

    assert "could not be completed" in result["final_answer"].lower()
    assert "route" not in result
    assert event_types(result) == ["completed"]


def test_finalize_node_emits_completion_event():
    result = nodes.finalize_node({})

    assert result["events"] == [
        {
            "node": "finalize",
            "event_type": "completed",
            "message": "workflow finished",
            "latency_ms": 0,
            "metadata": {},
        }
    ]
