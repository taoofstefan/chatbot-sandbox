"""FastAPI dashboard for browsing runs and results."""

# mypy: disable-error-code="no-any-return"

from __future__ import annotations

import difflib
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import BackendSet
from .db import Database

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

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: int) -> HTMLResponse:
        run_row = db.get_run(run_id)
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        results = db.get_results(run_id)
        return templates.TemplateResponse(
            request,
            "run.html",
            {
                "run": _run_to_dict(run_row),
                "results": [_result_to_dict(r) for r in results],
            },
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
            d = _result_to_dict(r)
            d["diff_partner_id"] = first_id
            blocks.append(d)
        templates_ = request.app.state.templates
        return templates_.TemplateResponse(
            request,
            "compare.html",
            {
                "run": _run_to_dict(run_row),
                "prompt_id": prompt,
                "blocks": blocks,
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
            {"results": [_result_to_dict(r) for r in results]},
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
            {"r": _result_to_dict(r)},
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
                "a": _result_to_dict(ra),
                "b": _result_to_dict(rb),
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
            {"tag": tag, "results": [_result_to_dict(r) for r in rows]},
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
            {"r": _result_to_dict(r)},  # type: ignore[arg-type]
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
            {"r": _result_to_dict(r)},  # type: ignore[arg-type]
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
                "results": [_result_to_dict(r) for r in results],
            }
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


def _result_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = _row_to_dict(row)
    if isinstance(d.get("tags"), str):
        d["tag_list"] = [t for t in d["tags"].split(",") if t]
    else:
        d["tag_list"] = []
    return d


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
