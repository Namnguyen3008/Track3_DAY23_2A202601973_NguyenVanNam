"""Tests for memory and SQLite LangGraph checkpointers."""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph_agent_lab.persistence import build_checkpointer


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
