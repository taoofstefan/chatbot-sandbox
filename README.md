# Chatbot Sandbox

A CLI-first tool for benchmarking prompts across LLM backends (Ollama, OpenAI, Anthropic, Claude CLI, Codex CLI, any local model).

## Install

```bash
uv sync
```

## Quick start

```bash
# Scaffold sample prompt + backend files in the current directory
uv run cbs init

# Validate configs
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

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest
```
