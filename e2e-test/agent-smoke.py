"""Thin wrapper that drives one agentic-benchmark case through `cbs run-agent`.

Pre-Step 7 this script was the inline vehicle for the 8 agentic cases: it
hard-coded the prompt text, tools, validators, and fixtures, and ran the
agent loop by hand. Step 7 moved all of that into `agent-prompts.yaml` /
`agent-backends.yaml` and the `cbs run-agent` / `cbs judge` CLI commands.
This file is now a ~30-line shim that shells out to that CLI for a single
case, so the existing one-line invocation in the workflow still works:

    uv run python e2e-test/agent-smoke.py                       # case 1
    uv run python e2e-test/agent-smoke.py --case constraint-retention
    uv run python e2e-test/agent-smoke.py --no-judges           # skip judge panel

The real benchmark runner is `cbs run-agent -p agent-prompts.yaml -b
agent-backends.yaml`; see HANDOVER_AGENTIC.md Step 7.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 so model outputs containing non-ASCII
# characters (e.g. -> arrows, em-dashes) don't crash the Windows console
# whose default codepage is cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
PROMPTS = _HERE / "agent-prompts.yaml"
BACKENDS = _HERE / "agent-backends.yaml"
DB_PATH = _HERE / "agent-results.db"

# Cases come from agent-prompts.yaml; kept in sync so --help lists them.
CASES = [
    "failing-test-fix",
    "constraint-retention",
    "external-action-boundary",
    "failure-recovery",
    "regression-guard",
    "repo-pattern",
    "ambiguous-requirement",
    "workload-decomposition",
]
JUDGES = ["nemotron-3-ultra", "gemma4-31b", "glm-5.1"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive one agentic case through `cbs run-agent`.")
    parser.add_argument(
        "--case",
        default="failing-test-fix",
        help=f"case id to run (one of: {', '.join(CASES)})",
    )
    parser.add_argument(
        "--no-judges",
        action="store_true",
        help="skip the LLM-judge panel for a cheap re-run",
    )
    args = parser.parse_args()

    if args.case not in CASES:
        print(f"unknown case: {args.case!r}", file=sys.stderr)
        print(f"available cases: {', '.join(CASES)}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        "-m",
        "chatbot_sandbox",
        "run-agent",
        "-p",
        str(PROMPTS),
        "-b",
        str(BACKENDS),
        "--prompt",
        args.case,
        "--db",
        str(DB_PATH),
        "--notes",
        "smoke",
    ]
    if args.no_judges:
        cmd.append("--no-judges")
    else:
        cmd += ["--judges", *JUDGES]

    # Pass the process through directly so the CLI owns all output. The exit
    # code is the CLI's (0 on a successful run; non-zero only on a hard error).
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())