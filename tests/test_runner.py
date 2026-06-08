"""Tests for the matrix runner."""

from __future__ import annotations

import time
from pathlib import Path

from chatbot_sandbox.backends.base import Backend, RunResult
from chatbot_sandbox.config import BackendConfig, Prompt
from chatbot_sandbox.db import Database
from chatbot_sandbox.runner import RunContext, run_matrix


class _SleepBackend(Backend):
    """Test backend that sleeps `sleep_s` seconds and returns a fixed output."""

    def __init__(self, config: BackendConfig, sleep_s: float) -> None:
        super().__init__(config)
        self.sleep_s = sleep_s
        self.calls = 0

    def run(self, prompt: str) -> RunResult:
        self.calls += 1
        time.sleep(self.sleep_s)
        return RunResult(output=f"echo:{prompt}", model=self.model)


def _make_config(name: str) -> BackendConfig:
    return BackendConfig(name=name, type="command", model=f"{name}-model")


def test_run_matrix_serial_baseline(tmp_path: Path) -> None:
    """Serial run of 4 × 1s tasks takes ~4s; verifies the test scaffolding itself."""
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    cfg = _make_config("b1")
    backend = _SleepBackend(cfg, sleep_s=0.05)
    prompts = [Prompt(id=f"p{i}", text=str(i)) for i in range(4)]
    ctx = RunContext(run_id=run_id, db=db, parallel=1)
    t0 = time.perf_counter()
    rows = run_matrix(prompts, [backend], [cfg], ctx)
    elapsed = time.perf_counter() - t0
    assert len(rows) == 4
    assert elapsed >= 4 * 0.05
    assert backend.calls == 4


def test_run_matrix_parallel_faster_than_serial(tmp_path: Path) -> None:
    """4 × 1s tasks with parallel=4 finishes in well under 4s (acceptance: < 2s)."""
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    cfg = _make_config("b1")
    backend = _SleepBackend(cfg, sleep_s=1.0)
    prompts = [Prompt(id=f"p{i}", text=str(i)) for i in range(4)]
    ctx = RunContext(run_id=run_id, db=db, parallel=4)
    t0 = time.perf_counter()
    rows = run_matrix(prompts, [backend], [cfg], ctx)
    elapsed = time.perf_counter() - t0
    assert len(rows) == 4
    assert elapsed < 2.0, f"expected < 2s with -j 4, got {elapsed:.2f}s"


def test_run_matrix_progress_callback_fires_per_task(tmp_path: Path) -> None:
    """on_progress is called once per (prompt, backend) pair."""
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1", "b2"])
    cfg1 = _make_config("b1")
    cfg2 = _make_config("b2")
    b1 = _SleepBackend(cfg1, sleep_s=0.0)
    b2 = _SleepBackend(cfg2, sleep_s=0.0)
    prompts = [Prompt(id="p1", text="hi"), Prompt(id="p2", text="ho")]
    calls: list[str] = []
    ctx = RunContext(
        run_id=run_id, db=db, parallel=1, on_progress=lambda msg: calls.append(msg)
    )
    run_matrix(prompts, [b1, b2], [cfg1, cfg2], ctx)
    assert len(calls) == 4
    assert all("p1" in m or "p2" in m for m in calls)
    assert all("b1" in m or "b2" in m for m in calls)


def test_run_matrix_results_persisted(tmp_path: Path) -> None:
    """Each task inserts exactly one row into the results table."""
    db = Database(tmp_path / "r.db")
    run_id = db.create_run("set", ["b1"])
    cfg = _make_config("b1")
    backend = _SleepBackend(cfg, sleep_s=0.0)
    prompts = [Prompt(id="a", text="x"), Prompt(id="b", text="y")]
    ctx = RunContext(run_id=run_id, db=db, parallel=1)
    run_matrix(prompts, [backend], [cfg], ctx)
    rows = db.get_results(run_id)
    assert len(rows) == 2
    by_prompt = {r["prompt_id"]: r for r in rows}
    assert by_prompt["a"]["output"] == "echo:x"
    assert by_prompt["b"]["output"] == "echo:y"
