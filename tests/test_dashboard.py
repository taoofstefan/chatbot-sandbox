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


def test_compare_endpoint(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    rid_a, rid_b = _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/1/compare?prompt=p1")
    assert r.status_code == 200
    assert "compare-block" in r.text
    assert "b1" in r.text
    assert "b2" in r.text
    assert "100ms" in r.text
    assert "200ms" in r.text
    assert "hello" in r.text
    assert "world" in r.text
    assert f'href="/diff?a={rid_a}&b={rid_a}"' in r.text
    assert f'href="/diff?a={rid_b}&b={rid_a}"' in r.text


def test_compare_endpoint_missing_prompt(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/1/compare?prompt=does-not-exist")
    assert r.status_code == 404


def test_compare_endpoint_missing_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/99/compare?prompt=p1")
    assert r.status_code == 404


def test_scorecard_empty(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/scorecard")
    assert r.status_code == 200
    assert "No results yet" in r.text


def test_scorecard_aggregates(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    rid_a, _ = _seed(db)
    db.add_tag(rid_a, "good")
    db.insert_result(
        {
            "run_id": 1,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m1",
            "output": "ok",
            "error": None,
            "latency_ms": 50,
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": 0.001,
        }
    )
    db.insert_result(
        {
            "run_id": 1,
            "prompt_id": "p2",
            "backend_name": "b1",
            "model": "m1",
            "output": None,
            "error": "boom",
            "latency_ms": 10,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }
    )
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/scorecard")
    assert r.status_code == 200
    assert "<code>p1</code>" in r.text
    assert "<code>p2</code>" in r.text
    assert "good" in r.text
    body = r.text
    p1_pos = body.find("<code>p1</code>")
    p2_pos = body.find("<code>p2</code>")
    p1_row = body[p1_pos:p2_pos]
    assert "3" in p1_row
    assert "350ms" in p1_row
    assert "$" in p1_row
    p2_row = body[p2_pos:]
    assert "1" in p2_row


def test_run_new_form_renders(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/new")
    assert r.status_code == 200
    assert "New run" in r.text
    assert 'enctype="multipart/form-data"' in r.text


def test_run_create_redirects(tmp_path: Path) -> None:
    import sys

    db = Database(tmp_path / "r.db")
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    prompts = tmp_path / "prompts.yaml"
    backends = tmp_path / "backends.yaml"
    prompts.write_text(
        "name: t\nprompts:\n  - id: a\n    text: hi\n", encoding="utf-8"
    )
    backends.write_text(
        "backends:\n"
        "  - name: echo\n"
        "    type: command\n"
        f"    command: ['{sys.executable}', '-c', 'pass']\n"
        "    model: echo-v1\n",
        encoding="utf-8",
    )
    with prompts.open("rb") as pf, backends.open("rb") as bf:
        r = client.post(
            "/runs",
            files={
                "prompts_file": ("prompts.yaml", pf, "application/x-yaml"),
                "backends_file": ("backends.yaml", bf, "application/x-yaml"),
            },
            data={"notes": "from test", "parallel": "1"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    assert r.headers["location"] == "/runs/1"
    run_row = db.get_run(1)
    assert run_row is not None
    assert run_row["notes"] == "from test"
    import json
    assert json.loads(run_row["prompts_json"]) == [{"id": "a", "text": "hi"}]


def test_run_create_bad_yaml_shows_error(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    prompts = tmp_path / "prompts.yaml"
    backends = tmp_path / "backends.yaml"
    prompts.write_text("name: t\nprompts:\n  - {", encoding="utf-8")
    backends.write_text(
        "backends:\n  - name: b\n    type: ollama\n    model: m\n",
        encoding="utf-8",
    )
    with prompts.open("rb") as pf, backends.open("rb") as bf:
        r = client.post(
            "/runs",
            files={
                "prompts_file": ("prompts.yaml", pf, "application/x-yaml"),
                "backends_file": ("backends.yaml", bf, "application/x-yaml"),
            },
        )
    assert r.status_code == 400
    assert "failed to parse upload" in r.text
