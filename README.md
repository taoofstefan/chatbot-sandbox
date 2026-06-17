# Chatbot Sandbox

A CLI-first tool for benchmarking prompts across LLM backends (Ollama, OpenAI, Anthropic, Claude CLI, Codex CLI, any local model).

## Install

From PyPI (when published):

```bash
pip install chatbot-sandbox
cbs --help
# or, equivalently:
python -m chatbot_sandbox --help
```

For local development:

```bash
uv sync --extra dev
uv run cbs --help
```

## Quick start

```bash
# Scaffold sample prompt + backend files in the current directory
uv run cbs init

# Validate configs (also shows whether each backend's API key resolves)
uv run cbs validate -p prompts.yaml -b backends.yaml

# Preview the planned matrix without running it
uv run cbs run -p prompts.yaml -b backends.yaml --dry-run

# Actually run it
uv run cbs run -p prompts.yaml -b backends.yaml -j 4

# List runs
uv run cbs list

# Show a run's summary / full text / diff
uv run cbs show 1 -m summary
uv run cbs show 1 -m full
uv run cbs show 1 -m diff --against 2

# Tag and annotate results
uv run cbs tag 7 good-enough verbose
uv run cbs note 7 "clean answer, fast"

# Export to Markdown
uv run cbs export 1 -o exports/run-1.md

# Launch the web dashboard
uv run cbs dashboard --port 8000
```

## Config files

### `prompts.yaml`

```yaml
name: starter
description: First sanity-check prompts
prompts:
  - id: hello
    text: Say hello in one short sentence.
    tags: [smoke]
  - id: german-rewrite
    text: Translate to German: 'Good morning, how are you today?'
    tags: [german, translation]
```

### `backends.yaml`

```yaml
backends:
  - name: ollama-llama3
    type: ollama
    model: llama3.1:8b
    base_url: http://localhost:11434

  - name: openai-gpt4o-mini
    type: openai
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY

  - name: claude-sonnet-cli
    type: claude_cli
    command: ["claude", "-p", "--output-format", "text"]

  - name: codex-cli
    type: codex_cli
    command: ["codex", "exec", "-"]

  - name: anthropic-sonnet
    type: anthropic
    model: claude-3-5-sonnet-latest
    api_key_env: ANTHROPIC_API_KEY
    cost_per_1k_input: 0.003
    cost_per_1k_output: 0.015
```

## Backend types

| Type | Purpose | Required fields |
|---|---|---|
| `ollama` | Local Ollama HTTP API | `model`, optional `base_url` |
| `openai` | OpenAI or any OpenAI-compatible endpoint | `model`, optional `base_url`, `api_key_env` |
| `anthropic` | Anthropic API | `model`, `api_key_env` |
| `claude_cli` | Subprocess: `claude -p` | `command` (optional default provided) |
| `codex_cli` | Subprocess: `codex exec -` | `command` (optional default provided) |
| `command` | Any CLI; prompt passed on stdin | `command` |

The prompt text is sent on stdin for subprocess backends, which is the most portable way to handle multi-line input.

## Storage

All results land in a SQLite database (`results.db` by default). Schema is auto-created. Add tags, notes, export to markdown, replay a run against new backends.

## API keys

Keys are resolved per backend. Prefer the safer forms; the literal and CLI
forms still work but leak more easily.

- **Recommended — `api_key_env`**: name an environment variable in the
  backend's YAML entry (`api_key_env: OPENAI_API_KEY`). The value lives in your
  shell environment or a `.env` file, never in a tracked config.
- **Acceptable (local-only) — `.env` file**: load `KEY=VALUE` pairs with
  `--env-file .env`. Existing process env wins over the file.
- **Discouraged — literal `api_key`**: a key written directly in the YAML. It
  is convenient but ends up in your config file (and in git, if tracked). A run
  prints a warning when a backend uses a literal `api_key`, and the value is
  redacted before any snapshot is stored.
- **Avoid — `--api-key backend=value`**: a one-off CLI override. It works, but
  your shell history and process list can capture the value. Use it only for
  throwaway local runs, never on a shared machine.

Resolution precedence (highest first): `--api-key` override → `api_key_env`
(including values loaded from `--env-file`) → literal `api_key`. All four
paths remain supported; the guidance above is about which to reach for first.

Ollama accepts the same key as a `Bearer` token when a remote Ollama is fronted
by a reverse proxy that requires authentication.

```bash
# Recommended: env var (set in your shell or a .env file)
export OPENAI_API_KEY=sk-...
uv run cbs run -p p.yaml -b b.yaml

# Acceptable local-only: .env file
cat > .env <<EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
EOF
uv run cbs run -p p.yaml -b b.yaml --env-file .env

# Discouraged: literal in backends.yaml (triggers a warning; redacted if stored)
#   - name: openai-gpt4o
#     type: openai
#     api_key: sk-...            # prefer api_key_env: OPENAI_API_KEY

# Avoid: CLI override (may appear in shell history / process list)
# uv run cbs run -p p.yaml -b b.yaml --api-key openai-gpt4o=sk-...
```

Every run also stores a **redacted** snapshot of its backends config
(`backends_json`) and run metadata (`meta_json`: cbs version, command,
Python/platform) so a run can be replayed and audited without the original
config files. No key is ever persisted; `cbs replay` resolves keys fresh from
the environment at replay time.

## Dashboard

`cbs dashboard` starts a small FastAPI + HTMX UI on `http://127.0.0.1:8000`.
Features:

- Browse runs, view summaries and full outputs
- Tag and annotate results inline (and now per-run notes too)
- Pick any two results and diff them
- Filter by tag
- Substring search across all result outputs
- Scorecard page aggregating results per prompt
- Side-by-side compare view for one prompt across all backends
- Start a new run from the browser (upload `prompts.yaml` + `backends.yaml`)

## Editor autocompletion

`cbs schema` emits a JSON Schema for the `prompts.yaml` and `backends.yaml`
config models. Point your editor at the file to get field validation and
autocomplete for the `type` enum and other fields.

```bash
cbs schema --out schemas.json
# In VS Code, add to .vscode/settings.json:
#   "yaml.schemas": { "schemas.json": ["*prompts.yaml", "*backends.yaml"] }
```

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest
```

To build the wheel and sdist locally:

```bash
uv build
ls dist/
```
