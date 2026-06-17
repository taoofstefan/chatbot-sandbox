# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - unreleased

### Added
- `cbs schema` subcommand exporting JSON Schema for the prompt and backend
  config models; usable for editor autocompletion and config validation.
  The `BackendConfig.type` field now exposes an enum of allowed values in
  the generated schema.
- `python -m chatbot_sandbox` entry point (`__main__.py`) so the package
  is runnable as a module.
- `[project.urls]` block in `pyproject.toml` (Homepage, Repository, Issues,
  Changelog).
- Per-run editable notes in the dashboard (mirrors per-result notes).
- `/search` route in the dashboard for substring search across result
  outputs (case-insensitive).
- `cbs diff` subcommand for terminal unified diffs between two results.
- `cbs validate --strict` flag, exits non-zero if any backend has an
  unresolved key. Warn message now names the env var to set.
- Web dashboard run trigger: upload `prompts.yaml` and `backends.yaml`
  from the browser, run in the background.
- Live side-by-side `/runs/{id}/compare?prompt=...` view in the
  dashboard, one block per backend, with a pre-filled diff link.
- Per-prompt scorecard page at `/scorecard` aggregating backends
  tested, ok count, total latency, total cost, and top tag.
- Stored prompt text on each run (`runs.prompts_json`); replay uses the
  stored text by default, falls back to `--prompts` if the run predates
  storage.
- Reproducibility snapshots on every run (migration `0005`):
  `runs.backends_json` stores a **redacted** backends-config snapshot and
  `runs.meta_json` stores cbs version, invoking command, and Python/platform.
  `cbs replay` reproduces a run from its stored backends snapshot when
  `--backends` is omitted. No key is ever stored; keys resolve fresh from the
  environment at replay time.
- Runtime warning when a backend config embeds a literal `api_key` (in
  `cbs run`, `replay`, and `validate`); the literal value is redacted before
  any backends snapshot is stored.
- File-based SQL migrations under `src/chatbot_sandbox/migrations/`
  (0001 init, 0002 prompts_json), tracked via `PRAGMA user_version`.
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) running
  ruff, mypy, and pytest on every push and PR.
- Test coverage for the parallel branch of `run_matrix`, the on_progress
  callback, and HTTP backends (Ollama, OpenAI, Anthropic) via `respx`.

### Changed
- `cbs validate` warn message now names the specific env var
  the backend expects instead of the generic "set api_key or api_key_env".
- Replay prints a clear error when the original run has no stored prompt
  text and no `--prompts` file is given (previously a yellow warning with
  placeholder text).
- API key guidance rewritten: `api_key_env` is recommended, `.env` via
  `--env-file` is acceptable local-only, a literal `api_key` is discouraged
  (and now warns at run time), and `--api-key backend=value` is avoided
  (shell history can capture it). All four paths remain functional;
  resolution precedence is `--api-key` → `api_key_env` → literal `api_key`.
- `cbs replay --backends` is now optional: it defaults to the run's stored
  backends snapshot and overrides it when given.
- `e2e-test/report*.md` smoke-run exports are no longer tracked (untracked
  via `git rm --cached`, kept on disk) and gitignored — they are regenerable
  via `cbs export` and previously shipped real model outputs.

### Removed
- Unused `pytest-asyncio` dev dependency and the `asyncio_mode = "auto"`
  pytest config: no async test functions exist, the plugin wasn't installed
  in CI, and the option emitted an `Unknown config option` warning on every
  run. `uv.lock` updated accordingly.

### Fixed
- CI was red on `main`: `uv sync --dev` doesn't install the dev tooling (it's
  declared in `[project.optional-dependencies].dev`, but `--dev` targets
  `[dependency-groups]`), so `uv run ruff` failed with "Failed to spawn: ruff".
  Changed to `uv sync --extra dev` in CI, `AGENTS.md`, `README.md`, and
  `HANDOVER.md`.
- `[project.urls]` in `pyproject.toml` pointed at the placeholder
  `github.com/example/chatbot-sandbox`; now the real
  `github.com/taoofstefan/chatbot-sandbox`.

## [0.1.0] - initial release

- Initial MVP: prompt and backend YAML configs, run a matrix of
  prompts × backends, store results in SQLite, browse via FastAPI
  dashboard.
