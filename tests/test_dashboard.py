"""Tests for the FastAPI dashboard."""

from pathlib import Path

from fastapi.testclient import TestClient

from chatbot_sandbox.dashboard import create_app
from chatbot_sandbox.db import Database


def _seed(db: Database) -> tuple[int, int]:
    run_id = db.create_run("set", ["b1"], notes="seed")
    rid1 = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m1",
            "output": "hello",
            "error": None,
            "latency_ms": 100,
            "input_tokens": 5,
            "output_tokens": 1,
            "cost_usd": 0.0001,
        }
    )
    rid2 = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b2",
            "model": "m2",
            "output": "world",
            "error": None,
            "latency_ms": 200,
            "input_tokens": 5,
            "output_tokens": 1,
            "cost_usd": 0.0001,
        }
    )
    db.finish_run(run_id)
    return rid1, rid2


def test_index_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Recent runs" in r.text


def test_run_detail_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/1")
    assert r.status_code == 200
    assert "Run #1" in r.text
    assert "b1" in r.text


def test_api_runs_json(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/api/runs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["id"] == 1


def test_tag_via_post(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    rid_a, _ = _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.post(f"/results/{rid_a}/tags", data={"tag": "good-enough"})
    assert r.status_code == 200
    assert db.get_result(rid_a) is not None
    with db.connect() as conn:
        rows = conn.execute("SELECT tag FROM tags WHERE result_id=?", (rid_a,)).fetchall()
    assert any(row["tag"] == "good-enough" for row in rows)


def test_note_via_post(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    rid_a, _ = _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.post(f"/results/{rid_a}/notes", data={"note": "looks good"})
    assert r.status_code == 200
    assert db.get_result(rid_a)["notes"] == "looks good"


def test_diff_endpoint(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    rid_a, rid_b = _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/diff?a={rid_a}&b={rid_b}")
    assert r.status_code == 200
    assert "diff-header" in r.text
