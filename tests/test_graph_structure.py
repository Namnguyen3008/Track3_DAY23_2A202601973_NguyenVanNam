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
