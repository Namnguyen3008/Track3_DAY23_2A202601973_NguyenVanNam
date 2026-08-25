"""Offline tests for the LangGraph workflow structure and terminal paths."""

from __future__ import annotations

import pytest

from langgraph_agent_lab import graph as graph_module
from langgraph_agent_lab.state import Route, Scenario, initial_state, make_event

NODE_NAMES = {
    "intake",
    "classify",
    "tool",
    "evaluate",
    "answer",
    "clarify",
    "risky_action",
    "approval",
    "retry",
    "dead_letter",
    "finalize",
}

EXPECTED_EDGES = {
    ("__start__", "intake", False),
    ("intake", "classify", False),
    ("classify", "answer", True),
    ("classify", "tool", True),
    ("classify", "clarify", True),
    ("classify", "risky_action", True),
    ("classify", "retry", True),
    ("tool", "evaluate", False),
    ("evaluate", "retry", True),
    ("evaluate", "answer", True),
    ("answer", "finalize", False),
    ("clarify", "finalize", False),
    ("risky_action", "approval", False),
    ("approval", "tool", True),
    ("approval", "clarify", True),
    ("retry", "tool", True),
    ("retry", "dead_letter", True),
    ("dead_letter", "finalize", False),
    ("finalize", "__end__", False),
}


def test_graph_registers_all_nodes_and_documented_edges():
    compiled = graph_module.build_graph()
    view = compiled.get_graph()

    assert NODE_NAMES <= set(view.nodes)
    assert {
        (edge.source, edge.target, edge.conditional)
        for edge in view.edges
    } == EXPECTED_EDGES


@pytest.mark.parametrize(
    ("route", "max_attempts"),
    [
        (Route.SIMPLE.value, 3),
        (Route.TOOL.value, 3),
        (Route.MISSING_INFO.value, 3),
        (Route.RISKY.value, 3),
        (Route.ERROR.value, 1),
    ],
)
def test_every_route_finalizes_offline_and_dead_letter_preserves_error_route(
    monkeypatch, route: str, max_attempts: int
):
    def fake_classify_node(state):
        return {
            "route": route,
            "risk_level": "high" if route == Route.RISKY.value else "low",
            "events": [make_event("classify", "completed", f"offline route: {route}")],
        }

    def fake_answer_node(state):
        return {
            "final_answer": "offline answer",
            "events": [make_event("answer", "completed", "offline answer generated")],
        }

    monkeypatch.setattr(graph_module, "classify_node", fake_classify_node, raising=False)
    monkeypatch.setattr(graph_module, "answer_node", fake_answer_node, raising=False)

    compiled = graph_module.build_graph()
    state = initial_state(
        Scenario(id=f"offline-{route}", query="offline request", expected_route=Route(route))
    )
    state["max_attempts"] = max_attempts
    result = compiled.invoke(state)

    event_nodes = [event["node"] for event in result["events"]]
    assert "finalize" in event_nodes
    assert event_nodes[-1] == "finalize"

    if route == Route.ERROR.value:
        assert result["route"] == Route.ERROR.value
        assert "dead_letter" in event_nodes
    if route == Route.RISKY.value:
        assert event_nodes.index("risky_action") < event_nodes.index("approval")
        assert event_nodes.index("approval") < event_nodes.index("tool")


def test_rejected_approval_terminates_without_tool_execution(monkeypatch):
    def fake_classify_node(_state):
        return {
            "route": Route.RISKY.value,
            "risk_level": "high",
            "events": [make_event("classify", "completed", "offline risky route")],
        }

    def fake_approval_node(_state):
        return {
            "approval": {
                "approved": False,
                "reviewer": "offline-reviewer",
                "comment": "rejected",
            },
            "events": [make_event("approval", "completed", "offline rejection")],
        }

    monkeypatch.setattr(graph_module, "classify_node", fake_classify_node, raising=False)
    monkeypatch.setattr(graph_module, "approval_node", fake_approval_node, raising=False)

    result = graph_module.build_graph().invoke(
        initial_state(
            Scenario(id="offline-rejected", query="delete account", expected_route=Route.RISKY)
        )
    )

    event_nodes = [event["node"] for event in result["events"]]
    assert "clarify" in event_nodes
    assert "tool" not in event_nodes
    assert event_nodes[-1] == "finalize"


def test_retry_success_returns_to_answer_before_finalizing(monkeypatch):
    def fake_classify_node(_state):
        return {
            "route": Route.TOOL.value,
            "risk_level": "low",
            "events": [make_event("classify", "completed", "offline tool route")],
        }

    def fake_tool_node(state):
        result = "mock recovered result" if state.get("attempt", 0) else "ERROR: transient"
        return {
            "tool_results": [result],
            "events": [make_event("tool", "completed", result)],
        }

    def fake_answer_node(_state):
        return {
            "final_answer": "offline recovered answer",
            "events": [make_event("answer", "completed", "offline answer")],
        }

    monkeypatch.setattr(graph_module, "classify_node", fake_classify_node, raising=False)
    monkeypatch.setattr(graph_module, "tool_node", fake_tool_node, raising=False)
    monkeypatch.setattr(graph_module, "answer_node", fake_answer_node, raising=False)

    state = initial_state(
        Scenario(id="offline-retry", query="temporary outage", expected_route=Route.TOOL)
    )
    result = graph_module.build_graph().invoke(state)

    event_nodes = [event["node"] for event in result["events"]]
    assert event_nodes.count("retry") == 1
    assert event_nodes.count("tool") == 2
    assert "answer" in event_nodes
    assert "dead_letter" not in event_nodes
    assert event_nodes[-1] == "finalize"
