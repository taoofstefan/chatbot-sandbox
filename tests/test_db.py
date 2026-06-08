"""Tests for the database layer."""

from __future__ import annotations

import json
from pathlib import Path

from chatbot_sandbox.db import Database


def test_create_and_query(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set1", ["b1", "b2"], notes="n")
    rid = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m",
            "output": "hello",
            "error": None,
            "latency_ms": 123,
            "input_tokens": 10,
            "output_tokens": 20,
            "cost_usd": 0.0001,
            "tags": ["ok"],
        }
    )
    db.add_tag(rid, "good-enough")
    db.add_tag(rid, "ok")
    db.set_notes(rid, "looks fine")

    row = db.get_result(rid)
    assert row is not None
    assert row["output"] == "hello"
    assert row["latency_ms"] == 123

    runs = db.list_runs()
    assert any(r["id"] == run_id for r in runs)

    db.finish_run(run_id)
    run_row = db.get_run(run_id)
    assert run_row["finished_at"] is not None


def test_create_run_stores_prompts_json(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    prompts = [
        {"id": "p1", "text": "hello"},
        {"id": "p2", "text": "world"},
    ]
    run_id = db.create_run("set", ["b1"], prompts=prompts)
    run_row = db.get_run(run_id)
    assert run_row is not None
    assert run_row["prompts_json"] is not None
    assert json.loads(run_row["prompts_json"]) == prompts


def test_create_run_without_prompts_has_null(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    run_row = db.get_run(run_id)
    assert run_row is not None
    assert run_row["prompts_json"] is None


def test_migration_adds_prompts_json_to_existing_db(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            prompt_set_name TEXT,
            backend_names TEXT NOT NULL,
            notes TEXT DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO runs (started_at, backend_names) VALUES (?, ?)",
        ("2025-01-01T00:00:00Z", "b1"),
    )
    conn.commit()
    conn.close()

    db = Database(db_path)
    with db.connect() as c:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(runs)").fetchall()}
    assert "prompts_json" in cols
    legacy_run = db.get_run(1)
    assert legacy_run is not None
    assert legacy_run["prompts_json"] is None

