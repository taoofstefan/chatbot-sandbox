# AGENTS.md

This is the agent-facing README for the repo. Codex reads project-level
`AGENTS.md`; OpenCode uses it as its main rules file; Claude Code falls back
to it when no repo `CLAUDE.md` diverges. See [Tooling & skills](#tooling--skills)
for how that layering is meant to work.

## Project purpose

`chatbot-sandbox` (CLI: `cbs`, package on PyPI as `chatbot-sandbox`) is a
CLI-first tool for benchmarking prompts across LLM backends — Ollama, OpenAI,
Anthropic, the `claude` and `codex` CLIs, and any OpenAI-compatible or generic
command backend. Python ≥ 3.12, MIT, alpha.

It does two things:

1. **Prompt matrix runs.** Run a set of prompts × backends, store outputs in
   SQLite (`results.db`), then list/show/diff/export/tag/note/replay them and
   browse them in a small FastAPI + HTMX dashboard.
2. **Agentic benchmark** (newer, under `src/chatbot_sandbox/agent/`). Spin up an
   agent with filesystem + shell tools inside a per-run sandbox copied from a
   fixture repo, drive it to completion, auto-grade the result, and score it
   with an LLM judge panel. See `HANDOVER_AGENTIC.md` for the design doc.

The people it serves: developers comparing models/prompts, and anyone building
agent evals on top of the library API.

## Setup commands

```bash
uv sync --dev                       # install deps (dev extras: ruff, mypy, pytest, respx)
uv run cbs --help                   # CLI entry (== uv run python -m chatbot_sandbox)
uv run cbs dashboard --port 8000    # dev server = the dashboard (FastAPI + HTMX)
uv run pytest                       # tests
uv run ruff check .                 # lint
uv run mypy src                     # type check (strict)
uv build                            # wheel + sdist -> dist/
uv run python e2e-test/agent-smoke.py  # e2e agent run (needs a live Ollama backend)
```

CLI subcommands: `init`, `validate`, `run`, `list`, `show`, `export`,
`grade`, `tag`, `note`, `diff`, `replay`, `schema`, `types`, `version`,
`dashboard`. There is **no** `run-agent` CLI yet — agent runs are driven via
the library API (`chatbot_sandbox.agent.run_agent`) and the e2e smoke script.

## Working rules

- Prefer small vertical slices. Do not refactor unrelated code.
- Ask before adding production dependencies (`[project] dependencies` in
  `pyproject.toml`); dev-only tools go in `[project.optional-dependencies].dev`.
- Never edit secrets, credentials, or `.env` / `*.local.yaml` files. They are
  gitignored; keys are resolved at runtime, not stored in config. See
  `secrets.py` and `PRIVACY.md`.
- **Public examples must be synthetic only** — see `PRIVACY.md`. Anything under
  `examples/`, README snippets, test fixtures, exports, or any prompt/output
  shipped in the repo must be fabricated, never real.
- **Schema changes go through numbered migrations.** Add
  `src/chatbot_sandbox/migrations/NNNN_name.sql` (next 4-digit version); do
  not hand-edit the live DB. Follow the per-version guard pattern in
  `db.py::_apply_migration` so old databases migrate cleanly.
- **The agent sandbox is best-effort isolation, not a security boundary.**
  `agent/shell_tool.py` runs commands with `shell=True` behind a blocklist.
  Never loosen the blocklist or symlink handling without flagging it; real
  isolation (containers) is a future v2. See `agent/sandbox.py`.
- Judge panels must not include the model under test (design doc §4.2).
- Before finishing: run `ruff`, `mypy`, and the relevant `pytest`, and show the
  evidence. Don't say "done" without it.

## Architecture notes

Main modules (all under `src/chatbot_sandbox/`):

- `cli.py` — Typer app; every `cbs` subcommand. `DEFAULT_DB = results.db`.
- `config.py` — Pydantic models: `PromptSet`/`Prompt` (with `validators`),
  `BackendSet`/`BackendConfig`. `from_yaml` loaders; also powers `cbs schema`.
- `secrets.py` — `KeyResolver` / `build_resolver` / `parse_key_override`.
- `backends/` — `base.py` (`Backend`, `BackendError`, `ChatResponse`),
  `registry.py` (`build_backend`, `known_types`), and one file per type:
  `ollama`, `openai_backend`, `anthropic_backend`, `claude_cli`, `codex_cli`,
  `command`. To add a backend: new file + register in `registry.py`.
- `runner.py` — `run_matrix`: prompts × backends, serial or
  `ThreadPoolExecutor` (`-j N`), inserts `results` rows, runs inline validators.
- `graders.py` — inline validators / `KNOWN_CHECKS`; applied in runs and via
  `cbs grade`.
- `db.py` — SQLite layer (WAL mode, foreign keys on), file-based migrations.
  Tables: `runs`, `results`, `tags`, `agent_runs`, `tool_calls`, `judge_scores`.
- `compare.py` / `export.py` — diff, side-by-side, markdown export.
- `dashboard.py` — FastAPI + Jinja2/HTMX web UI; reads the same DB.
- `agent/` — agentic subsystem:
  - `driver.py` — the run loop + system prompt (`run_agent`, `grade_run`).
  - `state.py` — `RunState`, `ModelResponse`, `ToolCallRecord`.
  - `tools_base.py` — `Tool` / `ToolRegistry` / `ToolExecutor` / `ToolResult`.
  - `sandbox.py` — `Sandbox`: temp-dir copy of a fixture, path-traversal
    defense, no symlinks.
  - `shell_tool.py` — `run_shell` with the safety blocklist + output cap +
    timeout clamp.
  - `filesystem_tools.py`, `communication_tools.py` (`CommunicationStore`).
  - `sentinel.py` — parse assistant messages for tool calls (non-native
    function-calling format) and detect stop conditions.
  - `graders.py` (`grade_agent`, `KNOWN_AGENT_CHECKS`),
    `judges.py` (LLM judge panel + rubric scores).

Data flow:

- **Prompt run:** `prompts.yaml` + `backends.yaml` → `cbs run` →
  `build_resolver` (keys) → `build_backend` per backend → `run_matrix` →
  each `_execute_one` calls `backend.run(prompt.text)` and inserts a
  `results` row (+ inline validation if `prompt.validators`) →
  `db.finish_run`. `list/show/export/tag/note/diff/replay` and the dashboard
  all read `results.db`.
- **Agent run:** fixture repo → `Sandbox.from_fixture(copy=True)` →
  `run_agent` loop (model ↔ tools, via `sentinel` parse or native FC) →
  audit trail persisted to `agent_runs` + `tool_calls` → `grade_run`
  auto-grade → `judge_panel` → `judge_scores`.

Important boundaries:

- One SQLite file per workspace (`results.db`, overridable with `--db`); the
  schema only ever changes via numbered migrations.
- The sandbox copies the fixture (`copy=True`) so the agent's edits never touch
  the checked-in source. Every FS tool path resolves against `workdir`;
  absolute paths and `..` traversal are rejected; symlinks are not followed.
- API keys are never logged — `_key_status` masks to first/last chars.

## Testing rules

- **Unit tests:** `tests/test_*.py` cover config, db, runner, graders,
  backends (HTTP mocked with `respx`), dashboard, cli, secrets, and the agent
  subsystem (`agent_sandbox`, `agent_tools`, `agent_sentinel`,
  `agent_driver`, `agent_graders`, `agent_judges`). Run: `uv run pytest`
  (`asyncio_mode = auto`).
- **Fixture repos:** `tests/fixtures/repo-bug-1/` is a real mini repo (its own
  `pyproject.toml` + `tests/`) copied into a sandbox for agent runs. It is
  excluded from pytest collection via `norecursedirs` — do not let it look like
  a test module.
- **Integration:** `test_runner.py`, `test_db.py`, `test_db_agent_runs.py`
  exercise the runner + DB against a temp SQLite file.
- **E2E / browser:** `e2e-test/agent-smoke.py` drives the real agent loop
  against a live Ollama backend at `127.0.0.1:11434` (needs a model + API key),
  writing `e2e-test/agent-results.db` and `agent-smoke*.log`. It is **not** part
  of the default `pytest` suite (`testpaths = ["tests"]`); run it manually.
  The dashboard has a browser UI but no headless browser tests — verify by
  hand with `cbs dashboard`.
- **Required before commit:** `uv run ruff check .` clean, `uv run mypy src`
  clean (strict), `uv run pytest` green. Ruff: line-length 100, py312, selects
  `E F I B UP SIM RUF`, ignores `E501 B008 F821`.

## Done criteria

- `ruff`, `mypy`, and the relevant `pytest` all pass — shown, not asserted.
- Diff is minimal and focused; no unrelated formatting churn.
- If the schema changed, a new numbered migration exists and old DBs still
  migrate; if a backend type was added, it is registered in `registry.py`.
- User-facing behavior is documented (README/`CHANGELOG.md`) if changed.
- No real prompts, outputs, keys, or work data committed (see `PRIVACY.md`).

## Tooling & skills

How this repo's agent guidance is layered across tools:

- **This file (`AGENTS.md`) is the single source of project rules.** Codex reads
  it as project rules; OpenCode uses it as its main rules file; Claude Code
  falls back to it. Keep project-specific truth here, not in global files.
- **Global/personal defaults live outside the repo** — e.g. `~/.codex/AGENTS.md`
  and `~/.claude/CLAUDE.md` — and should stay short (Karpathy-style baseline:
  state assumptions, favor simplicity, make surgical changes, don't guess
  silently). Don't duplicate project rules there.
- **Repo `CLAUDE.md`** only when Claude-specific behavior must diverge from
  `AGENTS.md`; otherwise `AGENTS.md` is authoritative.
- **Reusable workflows are skills, not giant pasted blocks.** Put them at
  `.agents/skills/<skill-name>/SKILL.md`. OpenCode and Claude also discover
  skills from `.opencode/skills`, `.claude/skills`, and `.agents/skills`
  (plus their global equivalents), so `.agents/skills/` is the portable shared
  location. Don't start with many — grow the set on demand.

Recommended skill workflow (use selectively, not all at once):

- **Global behavior:** Karpathy-style rules — state assumptions, keep it
  simple, surgical changes, no silent guessing.
- **Before coding (unclear requirements):** Matt Pocock's grill-me /
  grill-with-docs — force alignment before implementing.
- **Non-trivial changes:** Addy's spec-driven-development →
  planning-and-task-breakdown → incremental-implementation →
  test-driven-development (spec → plan → build → test → review → ship).
- **Debugging:** Matt's `diagnose` or Addy's debugging-and-error-recovery —
  not a generic "fix this."
- **Before merge:** run code review, security review, and simplification as
  **separate passes** (Addy fans `/ship` out to reviewer/security/test personas
  before synthesis).
- **Long sessions:** use handoff so the next agent/session can continue
  without re-reading the whole conversation (this repo already keeps
  `HANDOVER.md` / `HANDOVER_AGENTIC.md` for exactly this).