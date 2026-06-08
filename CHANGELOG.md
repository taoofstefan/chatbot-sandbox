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

## [0.1.0] - initial release

- Initial MVP: prompt and backend YAML configs, run a matrix of
  prompts × backends, store results in SQLite, browse via FastAPI
  dashboard.
