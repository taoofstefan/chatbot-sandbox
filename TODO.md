# Chatbot Sandbox — TODO

Handover document for the next session. The planned MVP, quality-of-life, and
engineering-hygiene items (#1-#12) are all complete — see `CHANGELOG.md` and
`git log` for the per-feature commits. The active backlog is the
**Stretch / ideas** section below, plus the agentic-benchmark steps (7-10)
tracked in `HANDOVER_AGENTIC.md`.

Each completed item keeps a one-line status note for traceability.

---

## MVP gaps — done

### 1. Live side-by-side comparison — done
- **Status**: `/runs/{id}/compare?prompt={pid}` route + `compare.html`
  (commit `fae789e`); stacks one block per backend with model/latency headers
  and a diff link.

### 2. Token & cost aggregation per (prompt, tag) — done
- **Status**: `/scorecard` route + `scorecard.html` (commit `c01339a`); one row
  per prompt with backends_tested, ok_count, total_latency_ms, total_cost,
  top_tag.

### 3. Replay via stored prompt text — done
- **Status**: `runs.prompts_json` (migration `0002`) stores full prompt text at
  run creation; `cbs replay` reads it first and only falls back to `--prompts`.
  Editing `prompts.yaml` no longer changes a replay of an old run.
- **Extended in `0005`**: `runs.backends_json` stores a *redacted* backends
  config snapshot and `runs.meta_json` stores cbs version + command + platform,
  so `cbs replay` now reproduces a run without the original config files
  (`--backends` is optional and overrides the stored snapshot). Secrets are
  never stored; keys resolve fresh from the environment at replay time.

### 4. Web dashboard run trigger — done
- **Status**: `GET /runs/new` (form) + `POST /runs` + `run_new.html` create a
  run from uploaded/selected prompts + backends and redirect to `/runs/{id}`.

---

## Quality of life — done

### 5. `cbs diff` subcommand — done
- **Status**: `cbs diff <result_a> <result_b>` prints a unified diff
  (`cli.py:442`), mirroring the dashboard `/diff`.

### 6. Search across runs — done
- **Status**: `/search` route + `search.html`; `WHERE output LIKE ?`, results
  link back to the run. Full-text via SQLite FTS5 deferred (not needed yet).

### 7. Per-run notes roundtrip — done
- **Status**: `set_run_notes` in `db.py` + `POST /runs/{id}/notes` +
  `_run_note.html`; run notes are editable in the dashboard.

### 8. Config validation hardening — done
- **Status**: `cbs validate` prints `warn` lines for backends that embed a
  literal `api_key` and for auth-requiring backends whose key is unresolved
  (naming the env var); covered by `test_validate_warns_on_literal_api_key`.

---

## Engineering hygiene — done

### 9. CI workflow — done
- **Status**: `.github/workflows/ci.yml` (commit `7b14225`) runs ruff + mypy +
  pytest on push/PR to `main`.

### 10. Test coverage for the runner — done
- **Status**: `tests/test_runner.py` covers `run_matrix` parallelism
  (`test_run_matrix_parallel_faster_than_serial`) and the per-task progress
  callback (`test_run_matrix_progress_callback_fires_per_task`).

### 11. Test coverage for backends — done
- **Status**: `tests/test_backends_http.py` (respx) covers happy-path +
  401/500/unauthorized for Ollama, OpenAI, and Anthropic.

### 12. Schema migrations — done
- **Status**: Migrations live in `src/chatbot_sandbox/migrations/NNNN_*.sql`
  and are applied via `PRAGMA user_version` in `db._bootstrap_and_migrate`,
  with per-version guards in `_apply_migration` for legacy DBs. Current head
  is `0005_reproducibility.sql`. Add new columns/files here; never hand-edit an
  existing migration or the live schema.

---

## Stretch / ideas (the remaining backlog)

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
  `pip install chatbot-sandbox` and `cbs --help` works. Prep is done
  (`__main__.py`, `[project.urls]`, changelog — commit `44f8f1e`); the actual
  release upload is the remaining step.

---

## When you sit down tomorrow

1. Run `uv sync` and `uv run pytest` to confirm the baseline still passes
   (then `uv run ruff check . && uv run mypy src`).
2. The MVP/QoL/hygiene TODO items (#1-#12) are all done — pick from the
   **Stretch / ideas** section above, or continue the agentic benchmark via
   `HANDOVER_AGENTIC.md` (steps 7-10).
3. Schema evolves only through numbered migrations
   (`src/chatbot_sandbox/migrations/NNNN_*.sql`); never hand-edit the live
   schema or an existing migration.
4. Public examples stay synthetic (see `PRIVACY.md`); never commit real
   prompts, outputs, keys, or run data.
5. After each change, run `uv run ruff check . && uv run mypy src && uv run pytest`.
6. Commit messages follow the existing pattern: imperative subject line, blank
   line, body that lists what + why with bullet points per file.