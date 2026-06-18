"""Network-free tests for the `cbs run-agent` / `cbs judge` CLI commands.

Uses `type: command` backends that print scripted responses (the agent
backend prints the `<done/>` sentinel; the judge backends print fixed judge
JSON), so the whole agent loop + grading + judging path is exercised with no
network and deterministic output. Mirrors the CliRunner + `type: command`
pattern from ``tests/test_cli.py``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from chatbot_sandbox.cli import app
from chatbot_sandbox.db import Database

runner = CliRunner()

# Sentinel the agent driver parses as "finished with this final answer".
DONE_SENTINEL = "<done/><final_answer>ok</final_answer>"

# Fixed judge payload (5 axes, all valid). The judge panel parses this and
# records one judge_scores row per (judge, axis).
JUDGE_JSON = json.dumps(
    {
        "scores": {
            "planning": 4,
            "recovery": 4,
            "honesty": 5,
            "minimality": 4,
            "safety": 5,
        },
        "evidence": {
            "planning": "p",
            "recovery": "r",
            "honesty": "h",
            "minimality": "m",
            "safety": "s",
        },
    }
)


def _write_script(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def agent_env(tmp_path: Path) -> SimpleNamespace:
    """Scripted agent + judge backends and a 2-prompt agent prompts file.

    The agent backend prints the done sentinel immediately (1-step run, no
    tool calls). The two judge backends print the fixed judge JSON. Both
    prompts use an empty sandbox (no fixture) so the test is self-contained.
    """
    agent_script = _write_script(
        tmp_path / "agent_done.py",
        "import sys\nsys.stdout.write(" + repr(DONE_SENTINEL) + ")\n",
    )
    judge_script = _write_script(
        tmp_path / "judge.py",
        "import sys\nsys.stdout.write(" + repr(JUDGE_JSON) + ")\n",
    )
    backends = {
        "backends": [
            {
                "name": "agent-a",
                "type": "command",
                "model": "agent-a-model",
                "command": [sys.executable, str(agent_script)],
            },
            {
                "name": "judge-1",
                "type": "command",
                "model": "judge-1-model",
                "command": [sys.executable, str(judge_script)],
            },
            {
                "name": "judge-2",
                "type": "command",
                "model": "judge-2-model",
                "command": [sys.executable, str(judge_script)],
            },
        ]
    }
    backends_file = tmp_path / "backends.yaml"
    backends_file.write_text(yaml.safe_dump(backends), encoding="utf-8")

    prompts = {
        "name": "agent-test",
        "prompts": [
            {
                "id": "case-1",
                "text": "Do the thing.",
                "tags": ["t"],
                "agent": {"tools": ["read_file"], "max_steps": 5},
                "validators": {
                    "completed_normally": True,
                    "final_text_contains": "ok",
                },
            },
            {
                "id": "case-2",
                "text": "Do the other thing.",
                "tags": ["t"],
                "agent": {"tools": ["read_file"], "max_steps": 5},
                "validators": {
                    "completed_normally": True,
                    "final_text_contains": "ok",
                },
            },
        ],
    }
    prompts_file = tmp_path / "prompts.yaml"
    prompts_file.write_text(yaml.safe_dump(prompts), encoding="utf-8")
    return SimpleNamespace(
        prompts=prompts_file, backends=backends_file, db=tmp_path / "results.db"
    )


def _run_id(output: str) -> int:
    m = re.search(r"run_id=(\d+)", output)
    assert m, f"no run_id in output: {output!r}"
    return int(m.group(1))


def test_run_agent_happy_path(agent_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--no-judges",
            "--db",
            str(agent_env.db),
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = _run_id(result.output)

    db = Database(agent_env.db)
    agent_runs = db.list_agent_runs_for_run(run_id)
    assert len(agent_runs) == 2  # 2 prompts x 1 backend
    for ar in agent_runs:
        assert ar["completed_normally"] == 1
        assert ar["final_answer"] == "ok"
        # No tool calls: the scripted agent emits only the done sentinel.
        assert len(db.get_tool_calls_for_agent_run(ar["id"])) == 0

    # Auto-grade persisted and passing.
    results = db.get_results(run_id)
    assert len(results) == 2
    for r in results:
        rep = json.loads(r["validation_json"])
        assert all(c["passed"] for c in rep.values()), rep

    # No judge panel → no judge_scores.
    assert sum(
        len(db.get_judge_scores_for_agent_run(ar["id"])) for ar in agent_runs
    ) == 0
    assert "Agent run" in result.output  # summary table printed


def test_run_agent_with_judges(agent_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--judges",
            "judge-1",
            "--judges",
            "judge-2",
            "--db",
            str(agent_env.db),
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = _run_id(result.output)

    db = Database(agent_env.db)
    agent_runs = db.list_agent_runs_for_run(run_id)
    assert len(agent_runs) == 2
    # 2 judges (neither equals "agent-a") x 5 axes x 2 agent runs = 20 scores.
    total = sum(len(db.get_judge_scores_for_agent_run(ar["id"])) for ar in agent_runs)
    assert total == 2 * 5 * 2
    # Summary table rendered with judge data (the axis headers can be
    # truncated by Rich at the test terminal width, so check the title and a
    # median value rather than an exact header word).
    assert "Agent run" in result.output
    assert "4.0" in result.output


def test_no_judges_flag_overrides_judges(agent_env: SimpleNamespace) -> None:
    """--no-judges wins even when --judges is given."""
    result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--judges",
            "judge-1",
            "--no-judges",
            "--db",
            str(agent_env.db),
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = _run_id(result.output)
    db = Database(agent_env.db)
    assert sum(
        len(db.get_judge_scores_for_agent_run(ar["id"]))
        for ar in db.list_agent_runs_for_run(run_id)
    ) == 0


def test_judge_rerun_is_idempotent(agent_env: SimpleNamespace) -> None:
    # First, an agent run with no judges so we have a stored audit trail.
    run_result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--no-judges",
            "--db",
            str(agent_env.db),
        ],
    )
    assert run_result.exit_code == 0, run_result.output
    run_id = _run_id(run_result.output)

    judge_args = [
        "judge",
        str(run_id),
        "-b",
        str(agent_env.backends),
        "--judges",
        "judge-1",
        "--judges",
        "judge-2",
        "--db",
        str(agent_env.db),
    ]
    first = runner.invoke(app, judge_args)
    assert first.exit_code == 0, first.output
    db = Database(agent_env.db)
    agent_runs = db.list_agent_runs_for_run(run_id)
    after_first = sum(
        len(db.get_judge_scores_for_agent_run(ar["id"])) for ar in agent_runs
    )
    assert after_first == 2 * 5 * 2  # 2 judges x 5 axes x 2 agent runs

    # Re-running the panel must not append duplicates (clear_judge_scores).
    second = runner.invoke(app, judge_args)
    assert second.exit_code == 0, second.output
    after_second = sum(
        len(db.get_judge_scores_for_agent_run(ar["id"])) for ar in agent_runs
    )
    assert after_second == after_first


def test_run_agent_dry_run_writes_no_rows(agent_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--dry-run",
            "--db",
            str(agent_env.db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Planned agent matrix" in result.output
    # No run_id line in a dry-run.
    assert "run_id=" not in result.output
    db = Database(agent_env.db)
    assert db.list_runs(limit=10) == []


def test_max_steps_override_honored(tmp_path: Path) -> None:
    """An agent that never finishes must stop at the --max-steps override."""
    # This agent ignores stdin and prints plain prose (no tool call, no done),
    # so the driver nudges it until it exhausts the step budget.
    loop_script = _write_script(
        tmp_path / "agent_loop.py",
        "import sys\nsys.stdout.write('still working...\\n')\n",
    )
    backends = {
        "backends": [
            {
                "name": "looper",
                "type": "command",
                "model": "looper-model",
                "command": [sys.executable, str(loop_script)],
            }
        ]
    }
    backends_file = tmp_path / "backends.yaml"
    backends_file.write_text(yaml.safe_dump(backends), encoding="utf-8")
    prompts = {
        "name": "loop-test",
        "prompts": [
            {
                "id": "loop-1",
                "text": "Never finish.",
                "agent": {"tools": ["read_file"], "max_steps": 10},
            }
        ],
    }
    prompts_file = tmp_path / "prompts.yaml"
    prompts_file.write_text(yaml.safe_dump(prompts), encoding="utf-8")
    db_path = tmp_path / "results.db"

    result = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(prompts_file),
            "-b",
            str(backends_file),
            "--max-steps",
            "3",
            "--no-judges",
            "--db",
            str(db_path),
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = _run_id(result.output)
    db = Database(db_path)
    agent_runs = db.list_agent_runs_for_run(run_id)
    assert len(agent_runs) == 1
    # The override (3) wins over the prompt's max_steps (10).
    assert agent_runs[0]["total_steps"] == 3
    assert agent_runs[0]["completed_normally"] == 0


def test_parallel_matches_serial_row_count(agent_env: SimpleNamespace) -> None:
    serial = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "--no-judges",
            "--db",
            str(agent_env.db),
        ],
    )
    assert serial.exit_code == 0, serial.output
    serial_count = len(Database(agent_env.db).list_agent_runs_for_run(_run_id(serial.output)))

    db2 = agent_env.db.parent / "results2.db"
    par = runner.invoke(
        app,
        [
            "run-agent",
            "-p",
            str(agent_env.prompts),
            "-b",
            str(agent_env.backends),
            "--backend",
            "agent-a",
            "-j",
            "2",
            "--no-judges",
            "--db",
            str(db2),
        ],
    )
    assert par.exit_code == 0, par.output
    par_count = len(Database(db2).list_agent_runs_for_run(_run_id(par.output)))
    assert par_count == serial_count == 2


def test_validate_reports_agent_block(tmp_path: Path) -> None:
    prompts = {
        "name": "v",
        "prompts": [
            {
                "id": "a",
                "text": "hi",
                "agent": {"tools": ["read_file"], "max_steps": 8},
            }
        ],
    }
    f = tmp_path / "prompts.yaml"
    f.write_text(yaml.safe_dump(prompts), encoding="utf-8")
    result = runner.invoke(app, ["validate", "--prompts", str(f)])
    assert result.exit_code == 0, result.output
    assert "agent cases: 1" in result.output
    assert "agent case: a" in result.output
    assert "max_steps=8" in result.output


def test_validate_bad_fixture_warns_and_strict_fails(tmp_path: Path) -> None:
    prompts = {
        "name": "v",
        "prompts": [
            {
                "id": "a",
                "text": "hi",
                "agent": {
                    "tools": ["read_file"],
                    "max_steps": 5,
                    "fixture": "does/not/exist/repo",
                },
            }
        ],
    }
    f = tmp_path / "prompts.yaml"
    f.write_text(yaml.safe_dump(prompts), encoding="utf-8")

    warn_result = runner.invoke(app, ["validate", "--prompts", str(f)])
    assert warn_result.exit_code == 0, warn_result.output
    assert "fixture not found" in warn_result.output

    strict_result = runner.invoke(app, ["validate", "--prompts", str(f), "--strict"])
    assert strict_result.exit_code == 1
    assert "fixture not found" in strict_result.output