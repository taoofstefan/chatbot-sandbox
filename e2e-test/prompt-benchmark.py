#!/usr/bin/env python
"""Reusable prompt-benchmark helper for end-to-end CLI validation.

The script discovers available real backends (OpenAI/Anthropic/Claude/Codex/Ollama),
adds command backends as fallback, validates the matrix with --dry-run, then runs it.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKDIR = ROOT / ".tmp" / "prompt-benchmark"


def _has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _is_ollama_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _has_ollama_model(model: str) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as r:
            payload = json.loads(r.read().decode("utf-8"))
        return any(entry.get("name") == model for entry in payload.get("models", []))
    except Exception:
        return False


def _prompt_yaml() -> str:
    return """name: sandbox-smoke
prompts:
  - id: greeting
    text: Say hello in one short sentence.
  - id: math
    text: What is 12 + 8?
"""


def _backend_yaml(require_real: bool, command_only: bool) -> str:
    entries: list[str] = []

    def add_backend(name: str, backend_type: str, *, command: list[str] | None = None, extra: list[str] | None = None) -> None:
        entries.append(f"  - name: {name}")
        entries.append(f"    type: {backend_type}")
        for item in extra or []:
            entries.append(f"    {item}")
        if command is not None:
            entries.append("    command:")
            for part in command:
                entries.append(f'      - {part!r}')
        entries.append("")

    if command_only:
        add_backend(
            "cmd-echo-a",
            "command",
            command=["python", "-c", "import sys; print('A:' + sys.stdin.read().strip())"],
        )
        add_backend(
            "cmd-echo-b",
            "command",
            command=["python", "-c", "import sys; print('B:' + sys.stdin.read().strip())"],
        )
        return "backends:\n" + "\n".join(entries) + "\n"

    if os.environ.get("OPENAI_API_KEY"):
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        add_backend("openai-gpt4o-mini", "openai", extra=[f"model: {model}", "api_key_env: OPENAI_API_KEY"])

    if os.environ.get("ANTHROPIC_API_KEY"):
        model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        add_backend("anthropic-sonnet", "anthropic", extra=[f"model: {model}", "api_key_env: ANTHROPIC_API_KEY"])

    if _has_command("claude"):
        add_backend("claude-cli", "claude_cli")

    if _has_command("codex"):
        add_backend("codex-cli", "codex_cli")

    if _is_ollama_running():
        model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        if _has_ollama_model(model):
            add_backend(f"ollama-{model.replace(':', '-')}", "ollama", extra=[f"model: {model}"])

    if not entries:
        if require_real:
            raise SystemExit("No real backends discovered; set OPENAI_API_KEY/ANTHROPIC_API_KEY, install Claude/Codex, or run Ollama.")
        # Deterministic local fallback so the script still executes end-to-end.
        add_backend(
            "cmd-echo-a",
            "command",
            command=["python", "-c", "import sys; print('A:' + sys.stdin.read().strip())"],
        )
        add_backend(
            "cmd-echo-b",
            "command",
            command=["python", "-c", "import sys; print('B:' + sys.stdin.read().strip())"],
        )

    return "backends:\n" + "\n".join(entries) + "\n"


def _run_cli(args: list[str]) -> int:
    return subprocess.run(
        [sys.executable, "-m", "chatbot_sandbox", *args],
        check=False,
        cwd=ROOT,
        env={**os.environ, "UV_CACHE_DIR": str(ROOT / ".uv")},
    ).returncode


def _latest_run_id(db_path: Path) -> int | None:
    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT MAX(id) FROM runs").fetchone()
    return row[0] if row and row[0] is not None else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true", help="Show matrix only, do not execute.")
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="Fail when no non-command backends are available.",
    )
    parser.add_argument(
        "--command-only",
        action="store_true",
        help="Use only local command backends.",
    )
    parser.add_argument("--workdir", type=Path, default=WORKDIR)
    parsed = parser.parse_args()

    workdir = parsed.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    prompts_file = workdir / "prompts.yaml"
    backends_file = workdir / "backends.yaml"

    prompts_file.write_text(_prompt_yaml(), encoding="utf-8")
    backends_file.write_text(
        _backend_yaml(require_real=parsed.require_real, command_only=parsed.command_only),
        encoding="utf-8",
    )

    cmd = [
        "run",
        "--db",
        str(workdir / "results.db"),
        "-p",
        str(prompts_file),
        "-b",
        str(backends_file),
        "-j",
        str(parsed.jobs),
    ]
    if parsed.dry_run:
        cmd.append("--dry-run")
        return _run_cli(cmd)

    code = _run_cli(cmd)
    if code != 0:
        return code

    _run_cli(["list", "--db", str(workdir / "results.db")])
    run_id = _latest_run_id(workdir / "results.db")
    if run_id is not None:
        _run_cli(["show", str(run_id), "-m", "summary", "--db", str(workdir / "results.db")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
