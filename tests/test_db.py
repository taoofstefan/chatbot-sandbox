"""Tests for the database layer."""

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
