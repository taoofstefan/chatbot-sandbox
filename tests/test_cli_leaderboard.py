"""Tests for `cbs leaderboard`, `cbs export-agent`, and the dashboard
leaderboard view (agentic Step 10). Network-free: seeds agent_runs +
judge_scores + results rows directly into a temp DB."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chatbot_sandbox.cli import app
from chatbot_sandbox.dashboard import create_app as create_dash_app
from chatbot_sandbox.db import Database

runner = CliRunner()

_AXES = ("planning", "recovery", "honesty", "minimality", "safety")


def _seed_leaderboard(db: Database) -> int:
    """Two backends, one prompt, one agent_run each. b1 auto-passes; b2 fails
    one check. Each agent_run gets 2 judges x 5 axes of scores."""
    run_id = db.create_run(
        "agentic-set",
        ["b1", "b2"],
        notes="leaderboard seed",
        prompts=[{"id": "p1", "text": "do the thing"}],
    )
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "b1-model",
            "output": "done",
            "error": None,
            "latency_ms": 100,
            "validation_json": json.dumps(
                {
                    "completed_normally": {"passed": True, "detail": "ok"},
                    "test_passes": {"passed": True, "detail": "green"},
                }
            ),
        }
    )
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b2",
            "model": "b2-model",
            "output": "hmm",
            "error": None,
            "latency_ms": 200,
            "validation_json": json.dumps(
                {
                    "completed_normally": {"passed": True, "detail": "ok"},
                    "test_passes": {"passed": False, "detail": "red"},
                }
            ),
        }
    )
    ar_b1 = db.create_agent_run(run_id, "p1", "b1")
    ar_b2 = db.create_agent_run(run_id, "p1", "b2")
    db.finish_agent_run(ar_b1, final_answer="done", total_steps=2, completed_normally=True)
    db.finish_agent_run(ar_b2, final_answer="hmm", total_steps=5, completed_normally=False)

    # b1: planning scores 5, 4 -> median 4.5
    b1_scores = {"planning": [5, 4], "recovery": [5, 5], "honesty": [5, 4], "minimality": [4, 4], "safety": [5, 5]}
    # b2: planning scores 3, 4 -> median 3.5
    b2_scores = {"planning": [3, 4], "recovery": [2, 3], "honesty": [4, 4], "minimality": [3, 2], "safety": [4, 5]}
    for ar_id, scores in [(ar_b1, b1_scores), (ar_b2, b2_scores)]:
        for i, axis in enumerate(_AXES):
            for j, score in enumerate(scores[axis]):
                db.insert_judge_score(
                    ar_id,
                    axis,
                    f"judge{j + 1}",
                    score,
                    judge_model=f"judge{j + 1}-model",
                    evidence=f"{axis} evidence",
                    raw_response="{}",
                    latency_ms=10 * (i + 1),
                )
    db.finish_run(run_id)
    return run_id


def test_leaderboard_cli(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = _seed_leaderboard(db)
    r = runner.invoke(app, ["leaderboard", str(run_id), "--db", str(tmp_path / "r.db")])
    assert r.exit_code == 0, r.output
    assert "Leaderboard" in r.output
    assert "b1" in r.output
    assert "b2" in r.output
    assert "1/1" in r.output  # b1 auto pass
    assert "0/1" in r.output  # b2 auto pass (one check failed)
    assert "4.5" in r.output  # b1 planning median
    assert "3.5" in r.output  # b2 planning median


def test_leaderboard_cli_no_agent_data(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    db.finish_run(run_id)
    r = runner.invoke(app, ["leaderboard", str(run_id), "--db", str(tmp_path / "r.db")])
    assert r.exit_code == 0, r.output
    assert "no agent data" in r.output


def test_leaderboard_cli_missing_run(tmp_path: Path) -> None:
    Database(tmp_path / "r.db")
    r = runner.invoke(app, ["leaderboard", "999", "--db", str(tmp_path / "r.db")])
    assert r.exit_code != 0


def test_export_agent_writes_markdown(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = _seed_leaderboard(db)
    out = tmp_path / "lb.md"
    r = runner.invoke(
        app,
        ["export-agent", str(run_id), "-o", str(out), "--db", str(tmp_path / "r.db")],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Agent leaderboard" in text
    assert "b1" in text
    assert "b2" in text
    assert "1/1" in text
    assert "4.5" in text
    # Markdown table header with all 5 axes.
    for axis in _AXES:
        assert axis in text


def test_dashboard_leaderboard_route(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = _seed_leaderboard(db)
    app_dash = create_dash_app(tmp_path / "r.db")
    client = TestClient(app_dash)
    r = client.get(f"/runs/{run_id}/leaderboard")
    assert r.status_code == 200
    assert "Leaderboard" in r.text
    assert "b1" in r.text
    assert "b2" in r.text
    assert "1/1" in r.text
    assert "4.5" in r.text


def test_dashboard_leaderboard_missing_run(tmp_path: Path) -> None:
    app_dash = create_dash_app(tmp_path / "r.db")
    client = TestClient(app_dash)
    r = client.get("/runs/999/leaderboard")
    assert r.status_code == 404


def test_dashboard_leaderboard_empty_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    db.finish_run(run_id)
    app_dash = create_dash_app(tmp_path / "r.db")
    client = TestClient(app_dash)
    r = client.get(f"/runs/{run_id}/leaderboard")
    assert r.status_code == 200
    assert "No agent data" in r.text