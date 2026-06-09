"""Matrix runner: execute a set of prompts against a set of backends."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .backends import Backend
from .config import BackendConfig, Prompt
from .db import Database, now_iso
from .graders import grade as grade_output


@dataclass
class RunContext:
    run_id: int
    db: Database
    parallel: int = 1
    on_progress: Callable[[str], None] | None = None


def estimate_cost(
    cfg: BackendConfig,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    if cfg.cost_per_1k_input is None and cfg.cost_per_1k_output is None:
        return None
    in_cost = (input_tokens or 0) / 1000.0 * (cfg.cost_per_1k_input or 0.0)
    out_cost = (output_tokens or 0) / 1000.0 * (cfg.cost_per_1k_output or 0.0)
    total = in_cost + out_cost
    return round(total, 6) if total > 0 else 0.0


def _execute_one(
    backend: Backend,
    backend_cfg: BackendConfig,
    prompt: Prompt,
    ctx: RunContext,
) -> dict[str, object]:
    started = now_iso()
    try:
        result = backend.run(prompt.text)
    except Exception as e:  # backend programmer error
        result = type("R", (), {"error": f"backend exception: {e}", "output": "", "latency_ms": 0,
                                  "input_tokens": None, "output_tokens": None, "model": backend.model})()

    row = {
        "run_id": ctx.run_id,
        "prompt_id": prompt.id,
        "backend_name": backend.name,
        "model": getattr(result, "model", None) or backend_cfg.model,
        "output": getattr(result, "output", "") or "",
        "error": getattr(result, "error", None),
        "latency_ms": getattr(result, "latency_ms", 0),
        "input_tokens": getattr(result, "input_tokens", None),
        "output_tokens": getattr(result, "output_tokens", None),
        "cost_usd": estimate_cost(
            backend_cfg,
            getattr(result, "input_tokens", None),
            getattr(result, "output_tokens", None),
        ),
        "started_at": started,
        "tags": prompt.tags,
        "notes": prompt.notes,
    }
    result_id = ctx.db.insert_result(row)
    row["id"] = result_id

    # Grade against inline validators, if any. Skip when the model errored.
    if prompt.validators and not row["error"]:
        report = grade_output(str(row["output"] or ""), prompt.validators)
        row["validation"] = report
        ctx.db.set_validation(result_id, json.dumps(report))
    return row


def run_matrix(
    prompts: list[Prompt],
    backends: list[Backend],
    backend_cfgs: list[BackendConfig],
    ctx: RunContext,
) -> list[dict[str, object]]:
    """Execute the cartesian product prompts x backends, return inserted rows."""
    cfg_by_name = {c.name: c for c in backend_cfgs}
    tasks: list[tuple[Backend, BackendConfig, Prompt]] = [
        (b, cfg_by_name[b.name], p) for b in backends for p in prompts
    ]
    rows: list[dict[str, object]] = []
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        transient=True,
    )

    with progress:
        overall = progress.add_task("running", total=len(tasks))
        if ctx.parallel <= 1:
            for backend, cfg, prompt in tasks:
                row = _execute_one(backend, cfg, prompt, ctx)
                rows.append(row)
                progress.update(overall, advance=1)
                if ctx.on_progress:
                    status = "ERR" if row["error"] else "OK"
                    ctx.on_progress(
                        f"[{status}] {prompt.id} x {backend.name} ({row['latency_ms']}ms)"
                    )
        else:
            with ThreadPoolExecutor(max_workers=ctx.parallel) as ex:
                futures = {
                    ex.submit(_execute_one, b, cfg_by_name[b.name], p, ctx): (b, p)
                    for b, _, p in tasks
                }
                for fut in as_completed(futures):
                    row = fut.result()
                    rows.append(row)
                    progress.update(overall, advance=1)
                    if ctx.on_progress:
                        status = "ERR" if row["error"] else "OK"
                        b, p = futures[fut]
                        ctx.on_progress(
                            f"[{status}] {p.id} x {b.name} ({row['latency_ms']}ms)"
                        )
    return rows
