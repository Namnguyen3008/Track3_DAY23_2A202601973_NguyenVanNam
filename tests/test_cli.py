from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import langgraph_agent_lab.cli as cli


class _FakeGraph:
    def __init__(self, checkpointer: object) -> None:
        self.checkpointer = checkpointer
        self.invoke_calls: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.history_calls: list[dict[str, Any]] = []

    def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.invoke_calls.append((state, config))
        return {
            **state,
            "route": "simple",
            "final_answer": "offline answer",
            "events": [{"node": "answer"}],
        }

    def get_state_history(self, config: dict[str, Any]) -> Iterator[dict[str, Any]]:
        self.history_calls.append(config)
        yield {"checkpoint": "ordinary completed-run history"}


def test_sqlite_config_is_loadable_from_repository() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    config = yaml.safe_load(
        (repository_root / "configs" / "lab_sqlite.yaml").read_text(encoding="utf-8")
    )

    assert config == {
        "scenarios_path": "data/sample/scenarios.jsonl",
        "checkpointer": "sqlite",
        "database_url": "outputs/lab_checkpoints.sqlite",
        "report_path": "reports/lab_report.md",
    }


def test_run_scenarios_uses_configured_paths_and_does_not_infer_recovery_from_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenarios_path = tmp_path / "scenarios.jsonl"
    scenarios_path.write_text(
        "".join(
            json.dumps(
                {
                    "id": f"S{i:02d}",
                    "query": f"simple query {i}",
                    "expected_route": "simple",
                }
            )
            + "\n"
            for i in range(1, 7)
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "configured" / "report.md"
    output_path = tmp_path / "configured" / "metrics.json"
    database_path = tmp_path / "configured" / "checkpoints.sqlite"
    config_path = tmp_path / "lab.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "scenarios_path": str(scenarios_path),
                "checkpointer": "sqlite",
                "database_url": str(database_path),
                "report_path": str(report_path),
            }
        ),
        encoding="utf-8",
    )

    checkpointer = object()
    checkpointer_calls: list[tuple[str, str | None]] = []
    graphs: list[_FakeGraph] = []

    def fake_build_checkpointer(kind: str, database_url: str | None = None) -> object:
        checkpointer_calls.append((kind, database_url))
        return checkpointer

    def fake_build_graph(checkpointer: object | None = None) -> _FakeGraph:
        graph = _FakeGraph(checkpointer)
        graphs.append(graph)
        return graph

    monkeypatch.setattr(cli, "build_checkpointer", fake_build_checkpointer)
    monkeypatch.setattr(cli, "build_graph", fake_build_graph)

    result = CliRunner().invoke(
        cli.app,
        [
            "run-scenarios",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert checkpointer_calls == [("sqlite", str(database_path))]
    assert len(graphs) == 1

    graph = graphs[0]
    assert graph.checkpointer is checkpointer
    assert len(graph.invoke_calls) == 6
    assert len(graph.history_calls) == 6
    for (state, invoke_config), history_config in zip(
        graph.invoke_calls, graph.history_calls, strict=True
    ):
        assert state["thread_id"] == f"thread-{state['scenario_id']}"
        assert invoke_config is history_config
        assert invoke_config == {
            "configurable": {"thread_id": state["thread_id"]}
        }

    metrics = json.loads(output_path.read_text(encoding="utf-8"))
    assert metrics["total_scenarios"] == 6
    assert metrics["resume_success"] is False
    assert report_path.read_text(encoding="utf-8")
