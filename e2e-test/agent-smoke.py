"""1-case smoke test for the agent driver loop.

Wires the agent driver to the real ollama cloud backend and runs the
failing-test-fix fixture. Reports the audit trail, the auto-grade
report, and a panel of LLM-judge scores.

Usage:
    uv run python e2e-test/agent-smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 so model outputs containing non-ASCII
# characters (e.g. → arrows, em-dashes) don't crash the Windows console
# whose default codepage is cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from chatbot_sandbox.agent import (  # noqa: E402  (path setup above)
    Sandbox,
    ToolRegistry,
    grade_run,
    judge_panel,
    run_agent,
)
from chatbot_sandbox.backends.ollama import OllamaBackend  # noqa: E402
from chatbot_sandbox.config import BackendConfig  # noqa: E402
from chatbot_sandbox.db import Database  # noqa: E402
from chatbot_sandbox.secrets import build_resolver  # noqa: E402

ROOT = _ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "repo-bug-1"
DB_PATH = ROOT / "e2e-test" / "agent-results.db"
BACKEND_NAME = "minimax-m3"
MODEL = "minimax-m3:cloud"
BASE_URL = "http://127.0.0.1:11434"
MAX_STEPS = 25
TIMEOUT_S = 300
USE_NATIVE = False  # set to True to use Ollama's native function-calling format

# Judge panel: 3 cloud models, none of which is the model under test.
# Per design doc §4.2, models never grade themselves on the same case.
JUDGE_MODELS: list[tuple[str, str]] = [
    ("nemotron-3-ultra", "nemotron-3-ultra:cloud"),
    ("gemma4-31b", "gemma4:31b-cloud"),
    ("glm-5.1", "glm-5.1:cloud"),
]


def _build_backend(name: str, model: str) -> OllamaBackend:
    cfg = BackendConfig(
        name=name,
        type="ollama",
        model=model,
        base_url=BASE_URL,
        timeout=TIMEOUT_S,
    )
    return OllamaBackend(cfg, key_resolver=build_resolver(overrides={}, env_file=None))


def main() -> int:
    if not FIXTURE.exists():
        print(f"fixture missing: {FIXTURE}", file=sys.stderr)
        return 2

    backend = _build_backend(BACKEND_NAME, MODEL)
    judge_backends = [_build_backend(label, model) for label, model in JUDGE_MODELS]

    sb = Sandbox.from_fixture(FIXTURE)
    db = Database(DB_PATH)
    # Allocate the run + result row up front so we can persist things as we go.
    run_id = db.create_run(
        prompt_set_name="agentic-smoke",
        backend_names=[BACKEND_NAME],
        notes="q3 2026 agentic smoke",
        prompts=[{"id": "failing-test-fix", "text": "(set below)"}],
    )
    result_id = db.insert_result(
        {
            "run_id": run_id,
            "prompt_id": "failing-test-fix",
            "backend_name": BACKEND_NAME,
            "model": MODEL,
            "output": "",
            "error": None,
            "latency_ms": 0,
            "tags": ["agentic", "smoke"],
        }
    )
    agent_run_id = db.create_agent_run(
        run_id=run_id,
        prompt_id="failing-test-fix",
        backend_name=BACKEND_NAME,
    )
    try:
        registry = ToolRegistry.from_names(
            ["list_dir", "read_file", "edit_file", "write_file", "run_shell", "search_files"]
        )

        prompt = (
            "The pytest test suite in the current working directory is currently failing. "
            "Read the source file `word_tools.py` and the test file `tests/test_word_tools.py`, "
            "identify the bug, fix it, and run `pytest -q` to confirm all tests pass. "
            "Do not edit `README.md` or `pyproject.toml`. "
            "When done, write a short summary in <done/><final_answer>...</final_answer>."
        )

        # Validators from the design doc §5 Case 1.
        # NOTE: test_passes uses `pytest` directly (not `python -m pytest`) because
        # the sandbox shell resolves pytest.exe from PATH, whereas a fresh
        # `python` invocation may point at a different interpreter (e.g. the uv
        # cache python) that doesn't have pytest installed.
        validators = {
            "completed_normally": True,
            "test_passes": ["pytest", "-q"],
            "files_touched_forbidden": ["README.md", "pyproject.toml", "tests/__init__.py"],
            "files_touched_max": 2,
            "no_forbidden_tools": [
                "list_dir",
                "read_file",
                "edit_file",
                "write_file",
                "run_shell",
                "search_files",
            ],
            "tool_calls_within_budget": 25,
            "final_text_contains_all": ["word_tools.py"],
        }

        print(f"=== smoke: {BACKEND_NAME} ({MODEL}) ===")
        print(f"fixture: {FIXTURE}")
        print(f"sandbox: {sb.workdir}")
        print(f"db: {DB_PATH} (run_id={run_id}, agent_run_id={agent_run_id})")
        print()
        t0 = time.perf_counter()
        state = run_agent(
            user_prompt=prompt,
            sandbox=sb,
            registry=registry,
            chat=backend.chat,
            max_steps=MAX_STEPS,
            use_native_tool_calling=USE_NATIVE,
        )
        wall = time.perf_counter() - t0

        # Persist the agent run + every tool call.
        db.finish_agent_run(
            agent_run_id,
            final_answer=state.final_answer,
            total_steps=state.total_steps,
            completed_normally=state.completed_normally,
            final_messages_json=json.dumps(state.messages, default=str),
        )
        for tc in state.tool_calls:
            db.insert_tool_call(
                agent_run_id=agent_run_id,
                step_index=tc.step_index,
                tool_name=tc.tool_name,
                arguments=dict(tc.arguments),
                result=dict(tc.output),
                ok=tc.ok,
                error=tc.error,
                duration_ms=tc.duration_ms,
            )

        # Grade the run while the sandbox still exists (test_passes needs it).
        grade_report = grade_run(state, validators, sandbox=sb)

        # Persist the grade report in the results row (for the single-turn
        # dashboard) AND in the agent_runs row (for the agentic dashboard).
        db.set_validation(result_id, json.dumps(grade_report, default=str))

        print(f"=== run finished in {wall:.1f}s, {state.total_steps} steps ===")
        print(f"completed_normally: {state.completed_normally}")
        print(f"final_answer: {state.final_answer!r}")
        print(f"error: {state.error!r}")
        print()
        print("=== auto-grading ===")
        for name, info in grade_report.items():
            mark = "OK " if info["passed"] else "ERR"
            print(f"  {mark} {name}: {info['detail']}")
        passed_count = sum(1 for v in grade_report.values() if v["passed"])
        total = len(grade_report)
        print(f"\n  {passed_count}/{total} auto-checks passed")
        print()
        print("=== audit trail ===")
        for i, tc in enumerate(state.tool_calls, 1):
            mark = "OK " if tc.ok else "ERR"
            print(
                f"[step {tc.step_index} #{i}] {mark} {tc.tool_name} "
                f"({tc.duration_ms}ms) args={json.dumps(dict(tc.arguments), default=str)[:200]}"
            )
            if tc.error:
                print(f"  error: {tc.error[:200]}")
            elif tc.output:
                # Show a short preview of the output
                preview = json.dumps(dict(tc.output), default=str)[:200]
                print(f"  output: {preview}")

        # Show the diff the agent produced.
        print()
        print("=== sandbox state after run ===")
        for p in sorted(sb.list_files()):
            full = sb.workdir / p
            print(f"  {p}  ({full.stat().st_size} bytes)")

        auto_passed = all(v["passed"] for v in grade_report.values())

        # ------------------------------------------------------------------
        # LLM-judge panel: 3 cloud models, none of which is the model under
        # test. Skip silently if the user wants a fast smoke (set SKIP_JUDGES=1).
        # ------------------------------------------------------------------
        panel = None
        if not (ROOT / ".skip-judges").exists() and "--no-judges" not in sys.argv:
            print()
            print("=== LLM-judge panel ===")
            t0 = time.perf_counter()
            panel = judge_panel(
                state=state,
                judges=[(label, jb.chat) for (label, _model), jb in zip(JUDGE_MODELS, judge_backends, strict=True)],
                user_prompt=prompt,
            )
            judge_wall = time.perf_counter() - t0
            print(f"  panel finished in {judge_wall:.1f}s")
            for axis, score in panel.median_scores.items():
                print(f"  {axis}: median={score}/5")
            for r in panel.reports:
                marker = "[ok]" if r.error is None else "[err]"
                print(
                    f"    {marker} {r.model} ({r.latency_ms}ms) "
                    f"median={r.median_score()}/5"
                )
                if r.error:
                    print(f"      error: {r.error[:200]}")
            print()
            print("  per-judge scores:")
            for r in panel.reports:
                scores_str = ", ".join(f"{k}={v}" for k, v in r.scores().items())
                print(f"    {r.model}: {scores_str}")

            # Persist every judge report (one row per (judge, axis)).
            for r in panel.reports:
                evidence = r.evidence()
                for axis, score in r.scores().items():
                    db.insert_judge_score(
                        agent_run_id=agent_run_id,
                        rubric=axis,
                        judge_backend=r.model or "unknown",
                        judge_model=r.model,
                        score=score,
                        evidence=evidence.get(axis, ""),
                        raw_response=r.raw,
                        latency_ms=r.latency_ms,
                    )

        # Final bookkeeping.
        # Update the results row with the agent's final answer.
        db.set_validation(result_id, json.dumps(grade_report, default=str))
        # Patch the result's output to be the final answer (so `cbs show`
        # surfaces something useful).
        with db.connect() as conn:
            conn.execute(
                "UPDATE results SET output = ?, error = ?, latency_ms = ? WHERE id = ?",
                (state.final_answer or "", state.error, int(wall * 1000), result_id),
            )
        db.finish_run(run_id)

        print()
        print("=== persistence ===")
        print(f"  run_id={run_id} result_id={result_id} agent_run_id={agent_run_id}")
        print(f"  {len(state.tool_calls)} tool calls persisted")
        if panel is not None:
            n_scores = len(panel.reports) * 5
            print(f"  {n_scores} judge scores persisted ({len(panel.reports)} judges x 5 axes)")

        return 0 if auto_passed else 1
    finally:
        sb.cleanup()


if __name__ == "__main__":
    sys.exit(main())
