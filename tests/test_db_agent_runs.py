"""Tests for the agentic-run persistence layer (migration 0004)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatbot_sandbox.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "r.db")


# --- agent_runs -------------------------------------------------------------


def test_create_agent_run_returns_id(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    rid = db.create_agent_run(run_id, "p1", "b1")
    assert rid > 0
    row = db.get_agent_run(rid)
    assert row is not None
    assert row["run_id"] == run_id
    assert row["prompt_id"] == "p1"
    assert row["backend_name"] == "b1"
    assert row["completed_normally"] == 0
    assert row["total_steps"] == 0
    assert row["started_at"]  # set by default


def test_finish_agent_run_updates_state(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    rid = db.create_agent_run(run_id, "p1", "b1")
    db.finish_agent_run(
        rid,
        final_answer="all done",
        total_steps=4,
        completed_normally=True,
        final_messages_json=json.dumps([{"role": "assistant", "content": "done"}]),
    )
    row = db.get_agent_run(rid)
    assert row["final_answer"] == "all done"
    assert row["total_steps"] == 4
    assert row["completed_normally"] == 1
    assert row["finished_at"] is not None
    assert json.loads(row["final_messages_json"])[0]["content"] == "done"


def test_finish_agent_run_preserves_messages_when_not_replaced(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    rid = db.create_agent_run(
        run_id,
        "p1",
        "b1",
        final_messages_json=json.dumps([{"role": "user", "content": "hi"}]),
    )
    db.finish_agent_run(rid, final_answer="x", total_steps=1, completed_normally=True)
    # Without passing final_messages_json, the original is preserved.
    row = db.get_agent_run(rid)
    assert json.loads(row["final_messages_json"])[0]["content"] == "hi"


def test_list_agent_runs_for_run_orders_by_id(db: Database) -> None:
    run_id = db.create_run("set", ["b1", "b2"])
    a = db.create_agent_run(run_id, "p1", "b1")
    b = db.create_agent_run(run_id, "p1", "b2")
    rows = db.list_agent_runs_for_run(run_id)
    assert [r["id"] for r in rows] == [a, b]


def test_get_agent_run_for_result(db: Database) -> None:
    run_id = db.create_run("set", ["b1", "b2"])
    # Two results for the same prompt on different backends.
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "output": "x",
            "error": None,
            "latency_ms": 1,
            "tags": [],
        }
    )
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b2",
            "output": "y",
            "error": None,
            "latency_ms": 2,
            "tags": [],
        }
    )
    # Agent runs for each.
    a = db.create_agent_run(run_id, "p1", "b1")
    b = db.create_agent_run(run_id, "p1", "b2")
    # We can find the agent_run that matches a result_id.
    r1 = db.get_agent_run_for_result(1)
    r2 = db.get_agent_run_for_result(2)
    assert r1["id"] == a
    assert r2["id"] == b


# --- tool_calls ------------------------------------------------------------


def test_insert_tool_call_persists_arguments_and_result(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    tid = db.insert_tool_call(
        aid,
        step_index=1,
        tool_name="read_file",
        arguments={"path": "src/foo.py"},
        result={"content": "x = 1", "lines": 1},
        ok=True,
        error=None,
        duration_ms=12,
    )
    assert tid > 0
    rows = db.get_tool_calls_for_agent_run(aid)
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_name"] == "read_file"
    assert r["step_index"] == 1
    assert r["ok"] == 1
    assert json.loads(r["arguments_json"]) == {"path": "src/foo.py"}
    assert json.loads(r["result_json"]) == {"content": "x = 1", "lines": 1}
    assert r["duration_ms"] == 12


def test_insert_tool_call_records_failure(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    db.insert_tool_call(
        aid,
        step_index=2,
        tool_name="edit_file",
        arguments={"path": "x", "old_text": "a", "new_text": "b"},
        result={},
        ok=False,
        error="old_text not found in file",
        duration_ms=3,
    )
    r = db.get_tool_calls_for_agent_run(aid)[0]
    assert r["ok"] == 0
    assert r["error"] == "old_text not found in file"


def test_tool_calls_ordered_by_step_index(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    db.insert_tool_call(aid, 3, "x", {}, {}, ok=True, error=None, duration_ms=0)
    db.insert_tool_call(aid, 1, "x", {}, {}, ok=True, error=None, duration_ms=0)
    db.insert_tool_call(aid, 2, "x", {}, {}, ok=True, error=None, duration_ms=0)
    rows = db.get_tool_calls_for_agent_run(aid)
    assert [r["step_index"] for r in rows] == [1, 2, 3]


# --- judge_scores ----------------------------------------------------------


def test_insert_judge_score_persists_fields(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    sid = db.insert_judge_score(
        aid,
        rubric="planning",
        judge_backend="judge-x",
        score=4,
        judge_model="judge-x:cloud",
        evidence="read 3 files before editing",
        raw_response="<full judge response>",
        latency_ms=2100,
    )
    assert sid > 0
    rows = db.get_judge_scores_for_agent_run(aid)
    assert len(rows) == 1
    r = rows[0]
    assert r["rubric"] == "planning"
    assert r["judge_backend"] == "judge-x"
    assert r["judge_model"] == "judge-x:cloud"
    assert r["score"] == 4
    assert r["evidence"] == "read 3 files before editing"
    assert r["raw_response"] == "<full judge response>"
    assert r["latency_ms"] == 2100


def test_judge_scores_ordered_by_rubric(db: Database) -> None:
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    for rubric in ("honesty", "planning", "minimality", "recovery", "safety"):
        db.insert_judge_score(aid, rubric, "judge-x", 3)
    rows = db.get_judge_scores_for_agent_run(aid)
    assert [r["rubric"] for r in rows] == sorted(
        {"honesty", "planning", "minimality", "recovery", "safety"}
    )


def test_multiple_judges_same_rubric_both_stored(db: Database) -> None:
    """The 3-judge panel writes 3 rows per rubric, not just the last one."""
    run_id = db.create_run("set", ["b1"])
    aid = db.create_agent_run(run_id, "p1", "b1")
    for backend, score in (("a", 5), ("b", 3), ("c", 4)):
        db.insert_judge_score(aid, "planning", backend, score)
    rows = db.get_judge_scores_for_agent_run(aid)
    assert len(rows) == 3
    scores = sorted(r["score"] for r in rows)
    assert scores == [3, 4, 5]


# --- migration -------------------------------------------------------------


def test_user_version_after_creating_fresh_db() -> None:
    """A new DB ends at >= 4 after migration 0004 runs."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        d_path = Path(d)
        db = Database(d_path / "fresh.db")
        assert db.user_version() >= 4


def test_legacy_v2_db_migrates_to_v4() -> None:
    """A pre-existing v2 DB (no results table) gets stamped through 3 and 4 without error."""
    import sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "legacy.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                prompt_set_name TEXT,
                backend_names TEXT NOT NULL,
                notes TEXT DEFAULT '',
                prompts_json TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO runs (started_at, backend_names, prompts_json) VALUES (?, ?, ?)",
            ("2025-01-01T00:00:00Z", "b1", "[]"),
        )
        conn.commit()
        conn.close()

        db = Database(db_path)
        # No crash; new tables exist (or are no-op'd) and version is current.
        assert db.user_version() >= 4
        # Original run row is intact.
        row = db.get_run(1)
        assert row is not None
        assert row["prompts_json"] == "[]"
