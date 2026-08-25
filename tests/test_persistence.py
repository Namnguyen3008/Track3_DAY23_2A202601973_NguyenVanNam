"""Tests for memory and SQLite LangGraph checkpointers."""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph_agent_lab import graph as graph_module
from langgraph_agent_lab.persistence import build_checkpointer
from langgraph_agent_lab.state import Route, Scenario, initial_state, make_event


def test_none_checkpointer_is_disabled():
    assert build_checkpointer("none") is None


def test_memory_checkpointer_returns_memory_saver():
    assert isinstance(build_checkpointer("memory"), MemorySaver)


def test_sqlite_checkpointer_creates_wal_database_and_keeps_connection_thread_safe(tmp_path):
    database_path = tmp_path / "checkpoints.sqlite"
    saver = build_checkpointer("sqlite", str(database_path))

    assert isinstance(saver, SqliteSaver)
    assert database_path.exists()
    assert saver.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert saver.conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
    ).fetchone()

    errors = []

    def read_from_worker_thread():
        try:
            saver.conn.execute("SELECT 1").fetchone()
        except Exception as exc:  # pragma: no cover - assertion reports the exception
            errors.append(exc)

    worker = threading.Thread(target=read_from_worker_thread)
    worker.start()
    worker.join()
    saver.conn.close()

    assert errors == []


def test_unknown_checkpointer_kind_is_rejected():
    with pytest.raises(ValueError, match="Unknown checkpointer kind"):
        build_checkpointer("unknown")


def test_sqlite_checkpoint_round_trip_across_connections(tmp_path, monkeypatch):
    def fake_classify_node(_state):
        return {
            "route": Route.SIMPLE.value,
            "risk_level": "low",
            "events": [make_event("classify", "completed", "offline simple route")],
        }

    def fake_answer_node(_state):
        return {
            "final_answer": "offline persisted answer",
            "events": [make_event("answer", "completed", "offline answer")],
        }

    monkeypatch.setattr(graph_module, "classify_node", fake_classify_node, raising=False)
    monkeypatch.setattr(graph_module, "answer_node", fake_answer_node, raising=False)

    database_path = tmp_path / "round-trip.sqlite"
    saver = build_checkpointer("sqlite", str(database_path))
    graph = graph_module.build_graph(checkpointer=saver)
    scenario = Scenario(id="persisted", query="how does this work", expected_route=Route.SIMPLE)
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}

    final_state = graph.invoke(state, config=config)
    saver.conn.close()

    reopened_saver = build_checkpointer("sqlite", str(database_path))
    reopened_graph = graph_module.build_graph(checkpointer=reopened_saver)
    snapshot = reopened_graph.get_state(config)
    history = list(reopened_graph.get_state_history(config))
    reopened_saver.conn.close()

    assert snapshot.values["route"] == final_state["route"] == Route.SIMPLE.value
    assert snapshot.values["thread_id"] == state["thread_id"]
    assert history
