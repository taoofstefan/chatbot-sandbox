"""Smoke tests for the CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from chatbot_sandbox.cli import app
from chatbot_sandbox.config import BackendSet, Prompt, PromptSet
from chatbot_sandbox.db import Database

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "chatbot-sandbox" in result.output


def test_types() -> None:
    result = runner.invoke(app, ["types"])
    assert result.exit_code == 0
    for t in ("ollama", "openai", "anthropic", "claude_cli", "codex_cli", "command"):
        assert t in result.output


def test_validate_prompts_yaml(tmp_path: Path) -> None:
    f = tmp_path / "prompts.yaml"
    f.write_text(
        "name: t\nprompts:\n  - id: a\n    text: hi\n    tags: [smoke]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--prompts", str(f)])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_validate_backends_yaml(tmp_path: Path) -> None:
    f = tmp_path / "backends.yaml"
    f.write_text(
        "backends:\n"
        "  - name: local-llama\n"
        "    type: ollama\n"
        "    model: llama3.1:8b\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--backends", str(f)])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_prompt_set_roundtrip() -> None:
    ps = PromptSet(
        name="n",
        prompts=[Prompt(id="a", text="hi", tags=["t1"]), Prompt(id="b", text="ho")],
    )
    assert ps.prompts[0].id == "a"
    assert ps.prompts[1].tags == []


def test_backend_set_find(tmp_path: Path) -> None:
    f = tmp_path / "b.yaml"
    f.write_text(
        "backends:\n"
        "  - name: a\n    type: ollama\n    model: m\n"
        "  - name: b\n    type: ollama\n    model: m\n",
        encoding="utf-8",
    )
    bs = BackendSet.from_yaml(f)
    picked = bs.find(["b", "a"])
    assert [b.name for b in picked] == ["b", "a"]


def test_diff_subcommand_prints_diff(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    rid_a = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m",
            "output": "hello world\nline two\n",
            "error": None,
            "latency_ms": 10,
        }
    )
    rid_b = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b2",
            "model": "m",
            "output": "hello WORLD\nline two\n",
            "error": None,
            "latency_ms": 20,
        }
    )
    db.finish_run(run_id)
    result = runner.invoke(
        app, ["diff", str(rid_a), str(rid_b), "--db", str(tmp_path / "r.db")]
    )
    assert result.exit_code == 0, result.output
    assert "hello world" in result.output
    assert "hello WORLD" in result.output


def test_diff_subcommand_bad_id(tmp_path: Path) -> None:
    Database(tmp_path / "r.db")
    result = runner.invoke(
        app, ["diff", "99", "100", "--db", str(tmp_path / "r.db")]
    )
    assert result.exit_code != 0
    assert "no such result" in result.output


def test_run_then_replay_uses_stored_prompt_text(tmp_path: Path) -> None:
    prompts = tmp_path / "prompts.yaml"
    backends = tmp_path / "backends.yaml"
    db_path = tmp_path / "r.db"

    prompts.write_text(
        "name: t\nprompts:\n  - id: a\n    text: ORIGINAL\n",
        encoding="utf-8",
    )
    backends.write_text(
        "backends:\n"
        "  - name: echo\n"
        "    type: command\n"
        f"    command: ['{sys.executable}', '-c', 'import sys; print(sys.stdin.read().strip())']\n"
        "    model: echo-v1\n",
        encoding="utf-8",
    )

    run = runner.invoke(
        app,
        [
            "run",
            "--prompts",
            str(prompts),
            "--backends",
            str(backends),
            "--db",
            str(db_path),
        ],
    )
    assert run.exit_code == 0, run.output

    prompts.write_text(
        "name: t\nprompts:\n  - id: a\n    text: EDITED\n",
        encoding="utf-8",
    )

    replay = runner.invoke(
        app,
        [
            "replay",
            "1",
            "--backends",
            str(backends),
            "--db",
            str(db_path),
        ],
    )
    assert replay.exit_code == 0, replay.output

    db = Database(db_path)
    new_run = db.get_run(2)
    assert new_run is not None
    assert new_run["prompts_json"] is not None
    stored = json.loads(new_run["prompts_json"])
    assert stored == [{"id": "a", "text": "ORIGINAL"}]


def test_replay_without_stored_prompts_needs_prompts_arg(tmp_path: Path) -> None:
    backends = tmp_path / "backends.yaml"
    db_path = tmp_path / "r.db"
    backends.write_text(
        "backends:\n"
        "  - name: echo\n"
        "    type: command\n"
        f"    command: ['{sys.executable}', '-c', 'pass']\n"
        "    model: echo-v1\n",
        encoding="utf-8",
    )

    db = Database(db_path)
    run_id = db.create_run("old", ["echo"], notes="predates storage")
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "a",
            "backend_name": "echo",
            "model": "echo-v1",
            "output": "x",
            "error": None,
            "latency_ms": 1,
        }
    )
    db.finish_run(run_id)

    result = runner.invoke(
        app,
        [
            "replay",
            str(run_id),
            "--backends",
            str(backends),
            "--db",
            str(db_path),
        ],
    )
    assert result.exit_code != 0
    assert "predates prompt-text storage" in result.output
