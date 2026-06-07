# Chatbot Sandbox — TODO

Handover document for the next session. Ordered by priority. Each item lists
goal, files involved, and a concrete acceptance test.

---

## MVP gaps (do these first)

### 1. Live side-by-side comparison
- **Goal**: A dedicated "compare" view that picks a run + a prompt and shows every
  backend's output stacked, with token/latency headers and a one-click diff link.
- **Files**: `src/chatbot_sandbox/dashboard.py`, new template
  `src/chatbot_sandbox/dashboard/templates/compare.html`.
- **Acceptance**: `GET /runs/{id}/compare?prompt={pid}` returns a 200 with one
  block per backend. Each block has the backend name, model, latency, output,
  and a link to `/diff?a={id}&b={id}` pre-filled with itself + the first sibling.

### 2. Token & cost aggregation per (prompt, tag)
- **Goal**: A small "scorecard" page: per prompt, show best/worst latency, total
  cost, tag counts. Helpful for the "best cheap model for this task" idea.
- **Files**: `src/chatbot_sandbox/dashboard.py` (new `scorecard` route), new
  template `scorecard.html`. Optional: new SQL view in `db.py`.
- **Acceptance**: `GET /scorecard` renders a table with one row per prompt
  and columns: backends_tested, ok_count, total_latency_ms, total_cost, top_tag.

### 3. Replay via stored prompt text
- **Goal**: `cbs replay <run_id>` currently warns that prompt text is lost. Store
  the original prompt text on the run row at creation time so replay can re-run
  exactly.
- **Files**: `src/chatbot_sandbox/db.py` (schema migration: add
  `prompts_json` column to `runs`), `src/chatbot_sandbox/runner.py` (capture
  prompt text on `create_run`), `src/chatbot_sandbox/cli.py` (replay reads from
  `prompts_json` first, falls back to `--prompts`).
- **Acceptance**: Run a set, edit `prompts.yaml`, replay the old run; the new
  run uses the *original* text, not the edited one. Test asserts equality of
  text via `db.get_run(run_id)['prompts_json']`.

### 4. Web dashboard run trigger
- **Goal**: Run new benchmarks from the dashboard. Form: upload prompts.yaml
  + backends.yaml (or pick from disk), choose backends/prompts, click Run.
- **Files**: `src/chatbot_sandbox/dashboard.py` (new `POST /runs` route), new
  template `run_new.html`. Use FastAPI's `UploadFile` for file inputs.
- **Acceptance**: Submitting the form creates a new run and redirects to
  `/runs/{new_id}`. Long runs should be backgrounded (FastAPI `BackgroundTasks`).

---

## Quality of life

### 5. `cbs diff` subcommand
- **Goal**: `cbs diff <result_a> <result_b>` prints a unified diff in the
  terminal, mirroring `/diff` in the dashboard.
- **Files**: `src/chatbot_sandbox/cli.py` (new `@app.command() diff`).
- **Acceptance**: With two stored results, `cbs diff 1 2` prints a colored diff
  and exits 0.

### 6. Search across runs
- **Goal**: A simple `WHERE output LIKE ?` search box in the dashboard, results
  link back to the run. Optional: full-text via SQLite FTS5.
- **Files**: `src/chatbot_sandbox/dashboard.py` (new `GET /search`).
- **Acceptance**: Searching for a unique word in one output returns exactly
  that result.

### 7. Per-run notes roundtrip
- **Goal**: Surface the `runs.notes` field in the dashboard as an editable
  textarea; currently only `results.notes` are editable.
- **Files**: `src/chatbot_sandbox/db.py` (add `set_run_notes`), dashboard route
  + template.
- **Acceptance**: Editing a run note and reloading the page persists the value.

### 8. Config validation hardening
- **Goal**: When `validate` is run without env vars set, fail with a clear
  message naming which backend needs which env var. Currently it just prints
  "missing" in green.
- **Files**: `src/chatbot_sandbox/cli.py` (`validate` function), maybe a new
  `requirements` field per backend in `config.py`.
- **Acceptance**: `cbs validate -b backends.yaml` with no env vars prints
  `warn` lines (not `ok`) for backends whose key is unresolved and type
  requires auth.

---

## Engineering hygiene

### 9. CI workflow
- **Goal**: GitHub Actions (or local pre-commit) running `ruff`, `mypy`,
  `pytest` on every push.
- **Files**: `.github/workflows/ci.yml`.
- **Acceptance**: Push a branch with a deliberate mypy error → CI fails with
  the expected line number.

### 10. Test coverage for the runner
- **Goal**: Cover the parallel branch in `runner.run_matrix` with a fake
  backend that sleeps; ensure `-j 4` actually parallelizes and the
  `on_progress` callback fires N times.
- **Files**: `tests/test_runner.py` (new).
- **Acceptance**: Test asserts wall-clock time for 4×1s tasks with `-j 4` is
  under 2s, and that the progress callback was called 4 times.

### 11. Test coverage for backends with a fake HTTP server
- **Goal**: Spin up a `pytest-httpserver` (or `respx`) mock for Ollama,
  OpenAI, Anthropic; assert that backends parse responses correctly and
  surface errors as `RunResult.error`.
- **Files**: `tests/test_backends_*.py` (new). Add `respx` or
  `pytest-httpserver` to dev deps.
- **Acceptance**: Each backend has a happy-path test and a 401/500 error test.

### 12. Schema migrations
- **Goal**: Currently `CREATE TABLE IF NOT EXISTS` won't add new columns. Move
  to a tiny migration system (e.g. `PRAGMA user_version` + ordered SQL files
  in `migrations/`).
- **Files**: `src/chatbot_sandbox/db.py` (new `migrate()` method),
  `src/chatbot_sandbox/migrations/0001_init.sql`, etc.
- **Acceptance**: After deleting and recreating the DB, the schema includes
  all columns from all migrations, and `PRAGMA user_version` matches the
  latest applied.

---

## Stretch / ideas (lower priority)

- **Streaming tokens live to the dashboard** during `cbs run` via SSE. Useful
  for long prompts; can be skipped until needed.
- **Prompt versioning**: Git-like diff between `prompts.yaml` snapshots. Maybe
  overkill at this scale.
- **Per-model leaderboard**: aggregate `tag` votes across runs into a "best
  model for X tag" ranking. Requires a tagging convention.
- **Plugin system for backends**: load third-party backends from a `plugins/`
  directory via entry points. Defer until there's a real third backend.
- **Async runner**: switch `httpx` calls to async; can mix with subprocess
  via `asyncio.to_thread`. Only worth it if API latency dominates.
- **JSON Schema export of configs**: helps editor autocompletion. Use
  `pydantic.json_schema()`.
- **Packaging**: publish to PyPI as `chatbot-sandbox` so others can
  `pip install chatbot-sandbox` and `cbs --help` works. Add a `[project.urls]`
  block and a `__main__.py`.

---

## When you sit down tomorrow

1. Run `uv sync` and `uv run pytest` to confirm the baseline still passes.
2. Pick **#1** (live side-by-side) if you want immediate dashboard value.
3. Pick **#3** (replay via stored text) if you care about reproducibility.
4. Pick **#9** (CI) if you want to start hosting this anywhere public.
5. After each change, run `uv run ruff check . && uv run mypy src && uv run pytest`.
6. Commit messages follow the existing pattern: imperative subject line, blank
   line, body that lists what + why with bullet points per file.
