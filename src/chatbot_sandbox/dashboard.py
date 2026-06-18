"""FastAPI dashboard for browsing runs and results."""

# mypy: disable-error-code="no-any-return"

from __future__ import annotations

import difflib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .backends import build_backend
from .config import BackendSet, PromptSet
from .db import Database, build_run_meta
from .runner import RunContext, run_matrix
from .secrets import build_resolver, redact_backend_config

_TEMPLATES_DIR = Path(__file__).parent / "dashboard" / "templates"
_STATIC_DIR = Path(__file__).parent / "dashboard" / "static"


def create_app(db_path: Path) -> FastAPI:
    db = Database(db_path)
    app = FastAPI(title="Chatbot Sandbox Dashboard")
    app.state.db = db
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        runs = db.list_runs(limit=50)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "runs": [_run_to_dict(r) for r in runs],
                "db_path": str(db_path),
            },
        )

    @app.get("/runs/new", response_class=HTMLResponse)
    def run_new_form(request: Request) -> HTMLResponse:
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(request, "run_new.html", {"error": None})

    @app.post("/runs")
    async def run_create(
        request: Request,
        background: BackgroundTasks,
        prompts_file: UploadFile = File(...),
        backends_file: UploadFile = File(...),
        notes: str = Form(""),
        parallel: int = Form(1),
    ) -> RedirectResponse:
        tmp = Path(tempfile.mkdtemp(prefix="cbs-upload-"))
        prompts_path = tmp / "prompts.yaml"
        backends_path = tmp / "backends.yaml"
        prompts_path.write_bytes(await prompts_file.read())
        backends_path.write_bytes(await backends_file.read())

        try:
            pset = PromptSet.from_yaml(prompts_path)
            bset = BackendSet.from_yaml(backends_path)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            templates_ = request.app.state.templates
            return templates_.TemplateResponse(
                request,
                "run_new.html",
                {"error": f"failed to parse upload: {e}"},
                status_code=400,
            )

        resolver = build_resolver()
        cfgs = bset.find(None)
        try:
            backends = [build_backend(c, key_resolver=resolver) for c in cfgs]
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            templates_ = request.app.state.templates
            return templates_.TemplateResponse(
                request,
                "run_new.html",
                {"error": f"failed to build backend: {e}"},
                status_code=400,
            )

        run_id = db.create_run(
            pset.name,
            [c.name for c in cfgs],
            notes=notes,
            prompts=[{"id": p.id, "text": p.text} for p in pset.prompts],
            backends=[redact_backend_config(c) for c in cfgs],
            meta=build_run_meta("dashboard"),
        )

        def _execute() -> None:
            try:
                ctx = RunContext(run_id=run_id, db=db, parallel=parallel)
                run_matrix(pset.prompts, backends, cfgs, ctx)
                db.finish_run(run_id)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        background.add_task(_execute)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: int) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = db.get_results(run_id)
        agent_run_count = len(db.list_agent_runs_for_run(run_id))
        return templates.TemplateResponse(
            request,
            "run.html",
            {
                "run": _run_to_dict(run_row),
                "results": [_result_to_dict(r, db) for r in results],
                "agent_run_count": agent_run_count,
            },
        )

    @app.post("/runs/{run_id}/notes", response_class=HTMLResponse)
    async def set_run_note(
        request: Request,
        run_id: int,
        note: str = Form(...),
    ) -> HTMLResponse:
        note_text = note.strip()
        if not note_text:
            raise HTTPException(status_code=400, detail="empty note")
        if db.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        db.set_run_notes(run_id, note_text)
        run_row = db.get_run(run_id)
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_run_note.html",
            {"run": _run_to_dict(run_row)},  # type: ignore[arg-type]
        )

    @app.get("/runs/{run_id}/compare", response_class=HTMLResponse)
    def run_compare(
        request: Request,
        run_id: int,
        prompt: str = Query(..., description="Prompt id to compare across backends"),
    ) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = [r for r in db.get_results(run_id) if r["prompt_id"] == prompt]
        if not results:
            raise HTTPException(
                status_code=404, detail=f"no results for prompt '{prompt}' in run {run_id}"
            )
        first_id = results[0]["id"]
        blocks: list[dict[str, Any]] = []
        for r in results:
            d = _result_to_dict(r, db)
            d["diff_partner_id"] = first_id
            blocks.append(d)
        templates_ = request.app.state.templates
        agent_summary = _agent_compare_summary(db, run_id, prompt)
        return templates_.TemplateResponse(
            request,
            "compare.html",
            {
                "run": _run_to_dict(run_row),
                "prompt_id": prompt,
                "blocks": blocks,
                "agent_summary": agent_summary,
                "axes": _JUDGE_AXES,
            },
        )

    @app.get("/runs/{run_id}/agent", response_class=HTMLResponse)
    def agent_run_list(request: Request, run_id: int) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        agent_rows = db.list_agent_runs_for_run(run_id)
        prompt_text = _prompt_text_map(run_row)
        results_by_key = _results_by_key(db, run_id)
        rows = [
            _agent_run_summary_row(ar, results_by_key, prompt_text, db)
            for ar in agent_rows
        ]
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "agent_run_list.html",
            {"run": _run_to_dict(run_row), "agent_runs": rows},
        )

    @app.get("/runs/{run_id}/agent/{agent_run_id}", response_class=HTMLResponse)
    def agent_run_detail(
        request: Request, run_id: int, agent_run_id: int
    ) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        ar = db.get_agent_run(agent_run_id)
        if ar is None or int(ar["run_id"]) != run_id:
            raise HTTPException(status_code=404, detail="agent run not found")
        prompt_text = _prompt_text_map(run_row)
        tool_calls = [
            _tool_call_to_dict(tc)
            for tc in db.get_tool_calls_for_agent_run(agent_run_id)
        ]
        judges = _judge_panel_for_agent_run(db, agent_run_id)
        auto_grade = _auto_grade_for(db, run_id, ar["prompt_id"], ar["backend_name"])
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "agent_run_detail.html",
            {
                "run": _run_to_dict(run_row),
                "agent_run": _agent_run_to_dict(ar),
                "prompt_text": prompt_text.get(ar["prompt_id"], ""),
                "tool_calls": tool_calls,
                "judges": judges,
                "axes": _JUDGE_AXES,
                "auto_grade": auto_grade,
            },
        )

    @app.get("/runs/{run_id}/leaderboard", response_class=HTMLResponse)
    def leaderboard_view(request: Request, run_id: int) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        rows = db.agent_leaderboard(run_id)
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "leaderboard.html",
            {
                "run": _run_to_dict(run_row),
                "rows": rows,
                "axes": _JUDGE_AXES,
            },
        )

    @app.get("/scorecard", response_class=HTMLResponse)
    def scorecard(request: Request) -> HTMLResponse:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.prompt_id AS prompt_id,
                    COUNT(*) AS backends_tested,
                    SUM(CASE WHEN r.error IS NULL OR r.error = '' THEN 1 ELSE 0 END)
                        AS ok_count,
                    COALESCE(SUM(r.latency_ms), 0) AS total_latency_ms,
                    COALESCE(SUM(r.cost_usd), 0.0) AS total_cost,
                    (
                        SELECT t.tag
                        FROM tags t
                        JOIN results r2 ON r2.id = t.result_id
                        WHERE r2.prompt_id = r.prompt_id
                        GROUP BY t.tag
                        ORDER BY COUNT(*) DESC, t.tag ASC
                        LIMIT 1
                    ) AS top_tag
                FROM results r
                GROUP BY r.prompt_id
                ORDER BY r.prompt_id
                """
            ).fetchall()
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "scorecard.html",
            {"rows": [dict(row) for row in rows]},
        )

    @app.get("/runs/{run_id}/results", response_class=HTMLResponse)
    def results_table(
        request: Request,
        run_id: int,
        prompt: str | None = Query(None),
    ) -> HTMLResponse:
        results = db.get_results(run_id)
        if prompt:
            results = [r for r in results if r["prompt_id"] == prompt]
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_results.html",
            {"results": [_result_to_dict(r, db) for r in results]},
        )

    @app.get("/results/{result_id}", response_class=HTMLResponse)
    def result_detail(request: Request, result_id: int) -> HTMLResponse:
        r = db.get_result(result_id)
        if r is None:
            raise HTTPException(status_code=404, detail="result not found")
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_result.html",
            {"r": _result_to_dict(r, db)},
        )

    @app.get("/diff", response_class=HTMLResponse)
    def diff_view(
        request: Request,
        a: int = Query(..., description="Result id A"),
        b: int = Query(..., description="Result id B"),
    ) -> HTMLResponse:
        ra = db.get_result(a)
        rb = db.get_result(b)
        if ra is None or rb is None:
            raise HTTPException(status_code=404, detail="result not found")
        diff = list(
            difflib.unified_diff(
                (ra["output"] or "").splitlines(),
                (rb["output"] or "").splitlines(),
                fromfile=f"{ra['backend_name']} ({ra['prompt_id']})",
                tofile=f"{rb['backend_name']} ({rb['prompt_id']})",
                n=3,
                lineterm="",
            )
        )
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_diff.html",
            {
                "a": _result_to_dict(ra, db),
                "b": _result_to_dict(rb, db),
                "diff_lines": diff,
            },
        )

    @app.get("/tags", response_class=HTMLResponse)
    def tag_index(request: Request) -> HTMLResponse:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT tag, COUNT(*) as n FROM tags GROUP BY tag ORDER BY n DESC"
            ).fetchall()
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "tag_index.html",
            {"tags": [dict(r) for r in rows]},
        )

    @app.get("/tags/{tag}", response_class=HTMLResponse)
    def tag_results(request: Request, tag: str) -> HTMLResponse:
        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM results r
                JOIN tags t ON t.result_id = r.id
                WHERE t.tag = ?
                ORDER BY r.id DESC LIMIT 100
                """,
                (tag,),
            ).fetchall()
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_tag_results.html",
            {"tag": tag, "results": [_result_to_dict(r, db) for r in rows]},
        )

    @app.post("/results/{result_id}/tags", response_class=HTMLResponse)
    async def add_tag(
        request: Request,
        result_id: int,
        tag: str = Form(...),
    ) -> HTMLResponse:
        tag = tag.strip()
        if not tag:
            raise HTTPException(status_code=400, detail="empty tag")
        if db.get_result(result_id) is None:
            raise HTTPException(status_code=404, detail="result not found")
        db.add_tag(result_id, tag)
        r = db.get_result(result_id)
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_result.html",
            {"r": _result_to_dict(r, db)},  # type: ignore[arg-type]
        )

    @app.post("/results/{result_id}/notes", response_class=HTMLResponse)
    async def add_note(
        request: Request,
        result_id: int,
        note: str = Form(...),
    ) -> HTMLResponse:
        note_text = note.strip()
        if not note_text:
            raise HTTPException(status_code=400, detail="empty note")
        if db.get_result(result_id) is None:
            raise HTTPException(status_code=404, detail="result not found")
        db.set_notes(result_id, note_text)
        r = db.get_result(result_id)
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "_result.html",
            {"r": _result_to_dict(r, db)},  # type: ignore[arg-type]
        )

    @app.get("/api/runs", response_class=JSONResponse)
    def api_runs(limit: int = Query(20, ge=1, le=200)) -> JSONResponse:
        return JSONResponse([_run_to_dict(r) for r in db.list_runs(limit=limit)])

    @app.get("/api/runs/{run_id}", response_class=JSONResponse)
    def api_run(run_id: int) -> JSONResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = db.get_results(run_id)
        return JSONResponse(
            {
                "run": _run_to_dict(run_row),
                "results": [_result_to_dict(r, db) for r in results],
            }
        )

    @app.get("/search", response_class=HTMLResponse)
    def search(
        request: Request,
        q: str = Query("", description="Substring to search in result outputs."),
    ) -> HTMLResponse:
        rows: list[sqlite3.Row] = []
        if q.strip():
            like = f"%{q.strip()}%"
            with db.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM results
                    WHERE LOWER(output) LIKE LOWER(?)
                    ORDER BY id DESC LIMIT 100
                    """,
                    (like,),
                ).fetchall()
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "search.html",
            {
                "q": q,
                "results": [_result_to_dict(r, db) for r in rows],
            },
        )

    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _run_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = _row_to_dict(row)
    if isinstance(d.get("backend_names"), str):
        d["backend_list"] = [b for b in d["backend_names"].split(",") if b]
    else:
        d["backend_list"] = []
    return d


def _result_to_dict(row: sqlite3.Row, db: Database | None = None) -> dict[str, Any]:
    d = _row_to_dict(row)
    prompt_tags: list[str] = []
    if isinstance(d.get("tags"), str):
        prompt_tags = [t for t in d["tags"].split(",") if t]
    user_tags: list[str] = []
    if db is not None and d.get("id") is not None:
        user_tags = db.get_tags_for_result(int(d["id"]))
    seen: set[str] = set()
    merged: list[str] = []
    for t in prompt_tags + user_tags:
        if t not in seen:
            seen.add(t)
            merged.append(t)
    d["tag_list"] = merged
    d["prompt_tag_list"] = prompt_tags
    d["user_tag_list"] = user_tags
    return d


# ---------------------------------------------------------------------------
# Agentic-run helpers (migration 0004: agent_runs, tool_calls, judge_scores)
# ---------------------------------------------------------------------------

_JUDGE_AXES = ("planning", "recovery", "honesty", "minimality", "safety")


def _parse_json(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _prompt_text_map(run_row: sqlite3.Row | None) -> dict[str, str]:
    """Parse a run's stored prompts_json snapshot into {prompt_id: text}."""
    out: dict[str, str] = {}
    if run_row is None:
        return out
    parsed = _parse_json(run_row["prompts_json"])
    if isinstance(parsed, list):
        for p in parsed:
            if isinstance(p, dict) and "id" in p and "text" in p:
                out[str(p["id"])] = str(p["text"])
    return out


def _results_by_key(db: Database, run_id: int) -> dict[tuple[str, str], sqlite3.Row]:
    """Index a run's results by (prompt_id, backend_name); latest wins."""
    out: dict[tuple[str, str], sqlite3.Row] = {}
    for r in db.get_results(run_id):
        key = (r["prompt_id"], r["backend_name"])
        if key not in out or r["id"] > out[key]["id"]:
            out[key] = r
    return out


def _auto_grade_from_result(row: sqlite3.Row) -> tuple[str, list[dict[str, Any]]]:
    """Return (auto_pass "n/total", [checks]) from a results.validation_json."""
    vj = _parse_json(row["validation_json"])
    if not isinstance(vj, dict) or not vj:
        return "-", []
    checks: list[dict[str, Any]] = []
    passed = 0
    for name, info in vj.items():
        ok = isinstance(info, dict) and bool(info.get("passed"))
        if ok:
            passed += 1
        checks.append(
            {
                "name": name,
                "passed": ok,
                "detail": str(info.get("detail", "")) if isinstance(info, dict) else "",
            }
        )
    return f"{passed}/{len(vj)}", checks


def _auto_grade_for(
    db: Database, run_id: int, prompt_id: str, backend_name: str
) -> list[dict[str, Any]]:
    for r in db.get_results(run_id):
        if r["prompt_id"] == prompt_id and r["backend_name"] == backend_name:
            _pass, checks = _auto_grade_from_result(r)
            return checks
    return []


def _agent_run_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = _row_to_dict(row)
    fa = d.get("final_answer") or ""
    d["final_answer_preview"] = fa[:200]
    d["completed"] = bool(d.get("completed_normally"))
    return d


def _agent_run_summary_row(
    row: sqlite3.Row,
    results_by_key: dict[tuple[str, str], sqlite3.Row],
    prompt_text: dict[str, str],
    db: Database,
) -> dict[str, Any]:
    d = _agent_run_to_dict(row)
    d["prompt_text"] = prompt_text.get(str(d.get("prompt_id") or ""), "")
    d["judge_count"] = len(db.get_judge_scores_for_agent_run(int(d["id"])))
    result = results_by_key.get((str(d.get("prompt_id", "")), str(d.get("backend_name", ""))))
    auto_pass, _checks = _auto_grade_from_result(result) if result is not None else ("-", [])
    d["auto_pass"] = auto_pass
    return d


def _tool_call_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = _row_to_dict(row)
    d["arguments"] = _parse_json(d.get("arguments_json"))
    d["result"] = _parse_json(d.get("result_json"))
    d["arguments_pretty"] = _pretty_json(d["arguments"], d.get("arguments_json", ""))
    d["result_preview"] = _truncate(_pretty_json(d["result"], d.get("result_json", "")), 800)
    return d


def _pretty_json(parsed: Any, raw: str) -> str:
    if parsed is None:
        return raw or ""
    return json.dumps(parsed, indent=2, default=str)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return float(s[n // 2])


def _judge_panel_for_agent_run(
    db: Database, agent_run_id: int
) -> list[dict[str, Any]]:
    """Group judge_scores into one dict per judge with per-axis scores+evidence."""
    by_judge: dict[str, dict[str, Any]] = {}
    for sc in db.get_judge_scores_for_agent_run(agent_run_id):
        name = sc["judge_backend"] or sc["judge_model"] or "unknown"
        j = by_judge.setdefault(
            name,
            {
                "name": name,
                "model": sc["judge_model"],
                "scores": {},
                "evidence": {},
                "latency_ms": 0,
            },
        )
        axis = sc["rubric"]
        j["scores"][axis] = int(sc["score"])
        j["evidence"][axis] = sc["evidence"] or ""
        j["latency_ms"] = max(j["latency_ms"], int(sc["latency_ms"] or 0))
    judges = list(by_judge.values())
    for j in judges:
        vals = [float(v) for v in j["scores"].values()]
        j["median"] = _median(vals)
    return judges


def _agent_compare_summary(
    db: Database, run_id: int, prompt_id: str
) -> list[dict[str, Any]]:
    """Per-backend judge medians + auto-grade for one (run, prompt)."""
    by_backend: dict[str, dict[str, Any]] = {}
    for r in db.get_results(run_id):
        if r["prompt_id"] != prompt_id:
            continue
        auto_pass, _checks = _auto_grade_from_result(r)
        by_backend[r["backend_name"]] = {
            "backend": r["backend_name"],
            "auto_pass": auto_pass,
            "medians": {},
            "completed": None,
            "steps": None,
        }
    for ar in db.list_agent_runs_for_run(run_id):
        if ar["prompt_id"] != prompt_id:
            continue
        b = by_backend.setdefault(
            ar["backend_name"],
            {
                "backend": ar["backend_name"],
                "auto_pass": "-",
                "medians": {},
                "completed": None,
                "steps": None,
            },
        )
        b["completed"] = bool(ar["completed_normally"])
        b["steps"] = int(ar["total_steps"])
        per_axis: dict[str, list[int]] = {a: [] for a in _JUDGE_AXES}
        for sc in db.get_judge_scores_for_agent_run(ar["id"]):
            if sc["rubric"] in per_axis:
                per_axis[sc["rubric"]].append(int(sc["score"]))
        for a in _JUDGE_AXES:
            if per_axis[a]:
                b["medians"][a] = _median([float(x) for x in per_axis[a]])
    return sorted(by_backend.values(), key=lambda d: str(d["backend"]))


def run_dashboard(
    db_path: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Convenience entrypoint used by the CLI: spins up uvicorn."""
    import uvicorn

    app = create_app(db_path)
    uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")


__all__ = ["BackendSet", "create_app", "run_dashboard"]
