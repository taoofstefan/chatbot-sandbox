"""Tests for the FastAPI dashboard."""

import json
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


def test_search_finds_matching_output(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m",
            "output": "the quick brown fox",
            "error": None,
            "latency_ms": 1,
        }
    )
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p2",
            "backend_name": "b1",
            "model": "m",
            "output": "hello world",
            "error": None,
            "latency_ms": 1,
        }
    )
    db.finish_run(run_id)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/search?q=fox")
    assert r.status_code == 200
    assert "the quick brown fox" in r.text
    assert "hello world" not in r.text


def test_search_case_insensitive(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "p1",
            "backend_name": "b1",
            "model": "m",
            "output": "Hello World",
            "error": None,
            "latency_ms": 1,
        }
    )
    db.finish_run(run_id)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/search?q=hello")
    assert r.status_code == 200
    assert "Hello World" in r.text


def test_search_empty_query_shows_prompt(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/search")
    assert r.status_code == 200
    assert "Type a substring" in r.text


def test_run_note_roundtrip(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _seed(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.post("/runs/1/notes", data={"note": "all good"})
    assert r.status_code == 200
    run_row = db.get_run(1)
    assert run_row["notes"] == "all good"
    r2 = client.get("/runs/1")
    assert r2.status_code == 200
    assert "all good" in r2.text
    assert "edit run note" in r2.text


def test_run_note_empty_rejected(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    Database(tmp_path / "r.db").create_run("set", ["b"])
    client = TestClient(app)
    r = client.post("/runs/1/notes", data={"note": "   "})
    assert r.status_code == 400


def test_run_note_missing_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.post("/runs/99/notes", data={"note": "x"})
    assert r.status_code == 404


def test_user_tag_visible_on_result_render(tmp_path: Path) -> None:
    """A user-added tag must show up in the rendered result detail."""
    db = Database(tmp_path / "r.db")
    _seed(db)
    db.add_tag(1, "user-tag-xyz")
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.post("/results/1/tags", data={"tag": "another-user-tag"})
    assert r.status_code == 200
    assert "another-user-tag" in r.text
    assert "user-tag-xyz" in r.text


# ---------------------------------------------------------------------------
# Agentic-run routes (Step 8)
# ---------------------------------------------------------------------------


def _seed_agent(db: Database) -> tuple[int, int]:
    """Seed a run with one agent_run, 3 tool_calls, a results row with a
    validation_json auto-grade report, and 2 judges x 5 axes of judge scores."""
    run_id = db.create_run(
        "agentic-set",
        ["minimax-m3"],
        notes="agent seed",
        prompts=[{"id": "failing-test-fix", "text": "Fix the failing test."}],
    )
    db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "failing-test-fix",
            "backend_name": "minimax-m3",
            "model": "minimax-m3:cloud",
            "output": "all done",
            "error": None,
            "latency_ms": 1234,
            "validation_json": json.dumps(
                {
                    "completed_normally": {
                        "passed": True,
                        "detail": "emitted final answer within budget",
                    },
                    "test_passes": {"passed": True, "detail": "pytest -q green"},
                    "files_touched_max": {"passed": True, "detail": "touched 1 file"},
                }
            ),
        }
    )
    ar_id = db.create_agent_run(run_id, "failing-test-fix", "minimax-m3")
    db.insert_tool_call(
        ar_id, 1, "read_file", {"path": "word_tools.py"},
        {"content": "def split(s): return s.split()"}, ok=True, error=None, duration_ms=12,
    )
    db.insert_tool_call(
        ar_id, 2, "edit_file", {"path": "word_tools.py", "old": "x", "new": "y"},
        {"ok": True}, ok=True, error=None, duration_ms=8,
    )
    db.insert_tool_call(
        ar_id, 3, "run_shell", {"cmd": ["pytest", "-q"]},
        {"rc": 0, "stdout": "3 passed"}, ok=True, error=None, duration_ms=450,
    )
    db.finish_agent_run(
        ar_id, final_answer="all done", total_steps=3, completed_normally=True,
    )
    for judge, model in [
        ("nemotron-3-ultra", "nemotron-3-ultra:cloud"),
        ("gemma4-31b", "gemma4:31b-cloud"),
    ]:
        for axis, score in [
            ("planning", 5), ("recovery", 4), ("honesty", 5),
            ("minimality", 4), ("safety", 5),
        ]:
            db.insert_judge_score(
                ar_id, axis, judge, score, judge_model=model,
                evidence=f"{judge} {axis} evidence", raw_response="{}", latency_ms=200,
            )
    db.finish_run(run_id)
    return run_id, ar_id


def test_agent_list_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/agent")
    assert r.status_code == 200
    assert "Agent runs" in r.text
    assert "failing-test-fix" in r.text
    assert "minimax-m3" in r.text
    assert f'href="/runs/{run_id}/agent/{ar_id}"' in r.text
    # Auto-grade pass count (3/3) and judge count (10) surface in the table.
    assert "3/3" in r.text
    assert ">10<" in r.text


def test_agent_list_missing_run(tmp_path: Path) -> None:
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get("/runs/99/agent")
    assert r.status_code == 404


def test_agent_list_empty_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    db.finish_run(run_id)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/agent")
    assert r.status_code == 200
    assert "No agent runs yet" in r.text


def test_agent_detail_renders(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/agent/{ar_id}")
    assert r.status_code == 200
    assert "Agent run #" in r.text
    # Auto-grade report with check names + pass markers.
    assert "completed_normally" in r.text
    assert "test_passes" in r.text
    assert "pass" in r.text
    # Judge panel: an axis header and an evidence block.
    assert "planning" in r.text
    assert "Evidence" in r.text
    # Audit trail shows the tool names.
    assert "read_file" in r.text
    assert "run_shell" in r.text
    # Final answer.
    assert "all done" in r.text


def test_agent_detail_audit_trail_in_step_order(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/agent/{ar_id}")
    assert r.status_code == 200
    body = r.text
    p_read = body.find("read_file")
    p_edit = body.find("edit_file")
    p_shell = body.find("run_shell")
    assert p_read != -1 and p_edit != -1 and p_shell != -1
    assert p_read < p_edit < p_shell


def test_agent_detail_missing_agent(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, _ = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/agent/9999")
    assert r.status_code == 404


def test_agent_detail_agent_run_not_in_run(tmp_path: Path) -> None:
    # An agent_run that exists but belongs to a different run_id is a 404.
    db = Database(tmp_path / "r.db")
    _run_id, ar_id = _seed_agent(db)
    other_run_id = db.create_run("other", ["b2"])
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{other_run_id}/agent/{ar_id}")
    assert r.status_code == 404


def test_agent_detail_missing_run(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    _run_id, ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/9999/agent/{ar_id}")
    assert r.status_code == 404


def test_run_detail_links_to_agent_view(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, _ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}")
    assert r.status_code == 200
    assert "Agent runs" in r.text
    assert f'href="/runs/{run_id}/agent"' in r.text


def test_compare_shows_judge_medians(tmp_path: Path) -> None:
    db = Database(tmp_path / "r.db")
    run_id, _ar_id = _seed_agent(db)
    app = create_app(tmp_path / "r.db")
    client = TestClient(app)
    r = client.get(f"/runs/{run_id}/compare?prompt=failing-test-fix")
    assert r.status_code == 200
    assert "Judge medians" in r.text
    assert "planning" in r.text
    assert "minimax-m3" in r.text
    # planning median for both judges = median(5,5) = 5.0
    assert "5.0" in r.text
