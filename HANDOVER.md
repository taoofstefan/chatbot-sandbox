# Handover — Ollama Cloud Model Benchmark

A plan for the next session: set up a personal "is the new model worth switching to?" benchmark using `chatbot-sandbox` (this repo) against the Ollama cloud models.

## What this is

You have an Ollama Pro subscription (no local GPU). The cloud models on `https://ollama.com/search?c=cloud` rotate as new ones drop. You want a way to know whether a new release is actually an upgrade over the one you're currently using, instead of relying on vibes.

This is **not** an academic benchmark. It is a repeatable, personal evaluation that:
- Runs the same prompts against different models
- Surfaces qualitative differences (instruction following, code style, structure)
- Tracks latency and cost
- Lets you eyeball outputs side-by-side and score them

`chatbot-sandbox` already does the heavy lifting: prompt × backend matrix, SQLite storage, side-by-side compare view in the dashboard, Markdown export, replay of exact prompts against new backends. Nothing new to build.

## What's already in place (from prior sessions)

- `e2e-test/` directory exists with `prompts.yaml`, `backends.yaml`, `results.db`, a working `replay-backends.yaml`, and a `report.md` from a 6-call smoke test.
- All 71 tests pass, ruff + mypy clean, CI workflow in place.
- `cbs` CLI works end-to-end against your local Ollama.
- Replay preserves the original prompt text (so future runs are comparable even if you edit `prompts.yaml` later).
- Dashboard has: per-prompt compare view, scorecard, search, diff, per-run and per-result notes/tags.

## Goal for next session

Build a 5-model × 5-prompt benchmark that:
1. Produces outputs you can actually judge ("yes, this model reasons better on code", "no, this one is just slower and gives the same answer").
2. Is reproducible — you can re-run it 3 months from now against whatever Ollama's current popular list is, and the results are comparable.
3. Takes ~10 minutes to run, so you'll actually do it.

## Step-by-step plan

### 1. Pick 5 models (10 min)

Go to https://ollama.com/search?c=cloud and pick 5 from the "Popular" list. Suggested mix (sized to show real differences):

| Slot | Suggested pick | Why |
|---|---|---|
| Your current default | `kimi-k2.6:cloud` | Already running; this is your baseline |
| Small/medium | `gemma4:12b` (or `qwen3.5:9b`) | Cheap, fast; tells you if bigger is worth it |
| Mid-size all-rounder | `qwen3.5:27b` or `:35b` | Often the sweet spot |
| Premium / big | `gpt-oss:120b` or `deepseek-v4-pro:cloud` | The "this should win" pick |
| Specialist | `qwen3-coder-next:cloud` or `nemotron-3-super:cloud` | Different training flavour |

Pick by what's currently popular and available — the list changes. Note the exact tag for each.

### 2. Write `prompts.yaml` (15 min)

Replace `e2e-test/prompts.yaml` with 5 prompts that actually stress the models. The point is to surface differences — easy prompts like "say hello" make every model look identical (as we saw in the smoke test).

The 5 prompts to write:

1. **Instruction following + constraints** — e.g. "How many times does the letter 'r' appear in 'strawberry'? Answer with just a number." Catches models that count syllables instead of letters, and that ramble instead of giving one number.

2. **Structured extraction** — "Extract the following into JSON with keys name/age/city: 'Jane is 34, lives in Berlin.'" Tests schema adherence: do they invent fields, change key names, wrap in markdown fences?

3. **Short code with edge cases** — e.g. "Write a Python decorator `@debounce(seconds)` that ensures a function is called at most once per N-second window. Include a brief docstring." Tests idiomatic Python, edge-case awareness (last call wins? first call wins?), brevity.

4. **Multi-step reasoning** — a classical logic puzzle. Example: "I have 3 boxes labeled 'apples', 'oranges', 'mixed'. All labels are wrong. I pick a fruit from the 'apples' box and it's an orange. Which box has what?" The answer requires deducing all 3 boxes from one observation. Models that guess vs. reason diverge here.

5. **Summarize + take a stance** — paste a 200-word real article or opinion piece, ask for a 2-3 sentence summary followed by an opinion on whether the policy is reasonable. Calibrates whether the model is wishy-washy ("there are pros and cons") or reasoned.

Each prompt gets a `tags:` field so you can filter in the dashboard later (e.g. `tags: [reasoning, code, structured-extraction]`).

### 3. Write `backends.yaml` (5 min)

```yaml
backends:
  - name: kimi-k2.6
    type: ollama
    model: kimi-k2.6:cloud
    base_url: http://127.0.0.1:11434
    timeout: 300  # generous; cloud models can be slow on long prompts

  - name: gemma4-12b
    type: ollama
    model: gemma4:12b
    base_url: http://127.0.0.1:11434
    timeout: 300

  # ... 3 more, same shape
```

Set `timeout: 300` (5 minutes). The default 120s timed out on a 14k-token summarization in the smoke test. Add `notes: "baseline run, q3 2026"` to the run later so you remember the era.

### 4. Dry-run, then real run (20 min)

```bash
cd e2e-test
uv run --project ".." cbs validate -p prompts.yaml -b backends.yaml
uv run --project ".." cbs run -p prompts.yaml -b backends.yaml --dry-run
uv run --project ".." cbs run -p prompts.yaml -b backends.yaml -j 5 \
    --db results.db --notes "q3 2026 cloud comparison"
```

`-j 5` runs all 5 backends in parallel; the matrix is 5×5 = 25 calls.

### 5. Browse, score, decide (30 min)

Open the dashboard: `uv run --project ".." cbs dashboard`

Useful routes:
- `/` — list of runs
- `/runs/1/compare?prompt=python-debounce` — side-by-side all 5 models on one prompt. This is the killer view.
- `/runs/1/compare?prompt=logic-puzzle` — see which models actually reason
- `/scorecard` — latency, cost, ok-rate per prompt
- `/search?q=def+debounce` — find every output containing a function definition
- `/diff?a=3&b=8` — quick side-by-side of two specific results

Score each prompt × model on three criteria in your head:
- **Correctness** (1-5): is the answer right?
- **Style** (1-5): would you actually use this output?
- **Speed** (1-5): feels snappy or sluggish?

Type the scores into a result note: `cbs note 5 "kimi: 4/5/3, gemma4: 3/5/5, ..."`

### 6. Export and file away (5 min)

```bash
uv run --project ".." cbs export 1 -o reports/q3-2026-cloud-comparison.md
```

Commit the report somewhere (a `reports/` dir, a personal gist, whatever). In 3 months when a new model drops, you re-run the same prompts and diff the reports.

### 7. When a new model appears (next quarter)

1. Add it to `backends.yaml` as a new entry
2. Run `cbs replay 1 -b backends-with-new-model.yaml` — this re-runs the original prompts against just the new model (or all of them; replay doesn't restrict backends, so you'll need to make a new backends file with just the new model + your baseline)
3. Compare in the dashboard
4. If the new model wins on the prompts that matter to you → switch your default. If not → keep using the old one and you've saved yourself a bad switch.

## Reuse pattern

Every quarter:
- Pull the current top 5 from `https://ollama.com/search?c=cloud`
- Drop a new line in `backends.yaml` per new model
- Re-run with `--notes "q4 2026 cloud comparison"`
- Diff the new `results.db` against the old one
- Update your default in the next iteration

The `cbs replay` workflow is purpose-built for this: stored prompt text + SQLite run history + Markdown export = a personal leaderboard over time, with zero ongoing infrastructure.

## Why not just use OpenAI Pro / Anthropic Pro?

(You said "I have openai pro sub, but that is nothing we can use here.")

Right — `chatbot-sandbox` supports OpenAI and Anthropic backends, so you *could* benchmark them too. But: the Ollama Pro sub gives you access to many models through one consistent API, and the model rotation is interesting (new ones drop monthly). OpenAI Pro is a flat subscription to a few specific models with no churn. Different shape, different motivation. If you ever want to add an OpenAI or Anthropic model to the comparison, just add a backend entry — `cbs` doesn't care.

## Useful commands cheat sheet

```bash
# Project root
cd "C:\Users\stefa_y9d2lgt\OneDrive\Coding\Chatbot Sandbox"

# Run
uv run cbs validate -p e2e-test/prompts.yaml -b e2e-test/backends.yaml
uv run cbs run -p e2e-test/prompts.yaml -b e2e-test/backends.yaml -j 5 \
    --db e2e-test/results.db --notes "..."
uv run cbs replay 1 -b e2e-test/backends.yaml --db e2e-test/results.db

# Inspect
uv run cbs list --db e2e-test/results.db
uv run cbs show 1 -m summary --db e2e-test/results.db
uv run cbs show 1 -m full --db e2e-test/results.db
uv run cbs diff 3 8 --db e2e-test/results.db  # two specific result ids
uv run cbs tag 5 "kimi-faster-on-code" --db e2e-test/results.db
uv run cbs note 5 "kimi 4/5/3, gemma4 3/5/5" --db e2e-test/results.db
uv run cbs export 1 -o e2e-test/report.md --db e2e-test/results.db
uv run cbs schema --out e2e-test/schemas.json

# Browse
uv run cbs dashboard   # then visit http://127.0.0.1:8000

# Tests / lint
uv run pytest
uv run ruff check .
uv run mypy src
```

## When you sit down next

1. `cd "C:\Users\stefa_y9d2lgt\OneDrive\Coding\Chatbot Sandbox"` and `uv sync --dev`
2. Pull up https://ollama.com/search?c=cloud in a browser
3. Pick 5 models following the mix in §1
4. Replace `e2e-test/prompts.yaml` with the 5 prompts in §2
5. Replace `e2e-test/backends.yaml` with the 5 backends in §3
6. Run the §4 commands
7. Spend 30 min in the dashboard scoring and comparing
8. Commit the report
9. Done until the next model drops
