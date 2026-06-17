"""Typer CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from . import __version__
from .backends import build_backend, known_types
from .backends.base import Backend, BackendError
from .compare import diff_outputs, side_by_side, summary_table
from .config import BackendConfig, BackendSet, Prompt, PromptSet
from .db import Database, build_run_meta
from .export import export_markdown
from .graders import KNOWN_CHECKS
from .graders import grade as grade_output
from .runner import RunContext, run_matrix
from .secrets import (
    KeyResolver,
    build_resolver,
    literal_key_warning,
    parse_key_override,
    redact_backend_config,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Benchmark prompts across LLM backends. CLI-first.",
)
console = Console()

DEFAULT_DB = Path("results.db")


def _db(path: Path | None) -> Database:
    return Database(path or DEFAULT_DB)


def _key_status(resolver: KeyResolver, cfg: BackendConfig) -> str:
    """Return a short, masked description of how a backend's key resolves."""
    key = resolver.resolve(cfg)
    if not key:
        return "[red]missing[/red]"
    if len(key) <= 8:
        return f"[green]{key[:2]}…[/green]"
    return f"[green]{key[:4]}…{key[-2:]}[/green]"


def _key_source(cfg: BackendConfig, resolver: KeyResolver) -> str:
    """Describe where the key would come from (for diagnostic messages)."""
    if cfg.name in resolver.overrides:
        return "--api-key"
    if cfg.api_key_env and resolver._lookup(cfg.api_key_env):
        return f"env:{cfg.api_key_env}"
    if cfg.api_key:
        return "api_key literal in config"
    if cfg.api_key_env:
        return f"env:{cfg.api_key_env} (unset)"
    return ""


def _warn_literal_keys(cfgs: list[BackendConfig]) -> None:
    """Warn once per backend that carries a literal api_key in its config."""
    for cfg in cfgs:
        msg = literal_key_warning(cfg)
        if msg:
            console.print(f"[yellow]warn[/yellow] {msg}")


def _backend_config_from_snapshot(snapshot: dict[str, Any]) -> BackendConfig:
    """Reconstruct a BackendConfig from a stored (redacted) snapshot.

    The stored ``api_key`` is either None or "[redacted]", so it is dropped and
    keys resolve fresh from the environment / overrides at replay time.
    """
    data = dict(snapshot)
    data.pop("api_key", None)
    return BackendConfig.model_validate(data)


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"chatbot-sandbox {__version__}")


@app.command()
def types() -> None:
    """List known backend types."""
    console.print(", ".join(known_types()))


@app.command()
def schema(
    kind: str = typer.Option(
        "all",
        "--kind",
        "-k",
        help="Which schema to emit: prompts, backends, or all.",
    ),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write to file instead of stdout."),
) -> None:
    """Print JSON Schema for the YAML config files.

    Useful for editor autocompletion (point your IDE at the schema
    URI/file) and for validating configs from other tools.
    """
    if kind not in ("prompts", "backends", "all"):
        raise typer.BadParameter("kind must be one of: prompts, backends, all")
    schemas: dict[str, object] = {}
    if kind in ("prompts", "all"):
        schemas["PromptSet"] = PromptSet.model_json_schema()
    if kind in ("backends", "all"):
        schemas["BackendSet"] = BackendSet.model_json_schema()
    payload = json.dumps(schemas, indent=2, sort_keys=False)
    if out is None:
        console.print(payload)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + "\n", encoding="utf-8")
        console.print(f"wrote {out}")


@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Directory to scaffold example files into."),
) -> None:
    """Scaffold a sample prompts.yaml and backends.yaml in PATH."""
    path.mkdir(parents=True, exist_ok=True)
    sample_prompts = path / "prompts.yaml"
    sample_backends = path / "backends.yaml"
    if not sample_prompts.exists():
        sample_prompts.write_text(
            yaml.safe_dump(
                {
                    "name": "starter",
                    "description": "First sanity-check prompts",
                    "prompts": [
                        {"id": "hello", "text": "Say hello in one short sentence.", "tags": ["smoke"]},
                        {
                            "id": "sum-lines",
                            "text": "Summarize the following text in 3 bullets:\n\n"
                            "The quick brown fox jumps over the lazy dog. "
                            "It then naps in the shade. The dog is happy.",
                            "tags": ["summarizing"],
                        },
                        {
                            "id": "german-rewrite",
                            "text": "Translate to German: 'Good morning, how are you today?'",
                            "tags": ["german", "translation"],
                        },
                    ],
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        console.print(f"wrote {sample_prompts}")
    if not sample_backends.exists():
        sample_backends.write_text(
            yaml.safe_dump(
                {
                    "backends": [
                        {
                            "name": "ollama-llama3",
                            "type": "ollama",
                            "model": "llama3.1:8b",
                            "base_url": "http://localhost:11434",
                        },
                        {
                            "name": "openai-gpt4o-mini",
                            "type": "openai",
                            "model": "gpt-4o-mini",
                            "api_key_env": "OPENAI_API_KEY",
                        },
                    ]
                },
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        console.print(f"wrote {sample_backends}")


@app.command()
def run(
    prompts_file: Path = typer.Option(..., "--prompts", "-p", help="YAML prompt set."),
    backends_file: Path = typer.Option(..., "--backends", "-b", help="YAML backend config."),
    only_backends: list[str] | None = typer.Option(
        None, "--backend", help="Restrict to these backend names (repeatable)."
    ),
    only_prompts: list[str] | None = typer.Option(
        None, "--prompt", help="Restrict to these prompt ids (repeatable)."
    ),
    parallel: int = typer.Option(1, "--parallel", "-j", help="Concurrent backend calls."),
    db_path: Path | None = typer.Option(None, "--db", help="SQLite path."),
    notes: str = typer.Option("", "--notes", help="Free-form note attached to the run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show matrix, do not execute."),
    api_key: list[str] | None = typer.Option(
        None,
        "--api-key",
        help="Override an API key: 'backend=value' (repeatable).",
    ),
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Load KEY=VALUE pairs from this file before resolving keys.",
    ),
) -> None:
    """Run a prompt set against a set of backends."""
    try:
        overrides = parse_key_override(api_key)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    resolver = build_resolver(overrides=overrides, env_file=env_file)

    pset = PromptSet.from_yaml(prompts_file)
    bset = BackendSet.from_yaml(backends_file)
    backends_cfg = bset.find(only_backends)

    prompts: list[Prompt] = pset.prompts
    if only_prompts:
        ids = set(only_prompts)
        prompts = [p for p in prompts if p.id in ids]
        missing = ids - {p.id for p in prompts}
        if missing:
            raise typer.BadParameter(f"unknown prompt id(s): {sorted(missing)}")

    matrix = [(p.id, b.name) for p in prompts for b in backends_cfg]
    table = Table(title="Planned matrix")
    table.add_column("#", justify="right")
    table.add_column("Prompt")
    table.add_column("Backend")
    table.add_column("Key")
    for i, (pid, bname) in enumerate(matrix, 1):
        cfg = next(b for b in backends_cfg if b.name == bname)
        key_status = _key_status(resolver, cfg)
        table.add_row(str(i), pid, bname, key_status)
    console.print(table)

    _warn_literal_keys(backends_cfg)

    if dry_run:
        console.print("[yellow]dry-run: not executing[/yellow]")
        return

    db = _db(db_path)
    run_id = db.create_run(
        pset.name,
        [b.name for b in backends_cfg],
        notes=notes,
        prompts=[{"id": p.id, "text": p.text} for p in prompts],
        backends=[redact_backend_config(b) for b in backends_cfg],
        meta=build_run_meta("run"),
    )
    console.print(f"[dim]run_id={run_id} db={db.path}[/dim]")

    backends: list[Backend] = []
    for cfg in backends_cfg:
        try:
            backends.append(build_backend(cfg, key_resolver=resolver))
        except BackendError as e:
            console.print(f"[red]skipping {cfg.name}: {e}[/red]")

    ctx = RunContext(run_id=run_id, db=db, parallel=parallel)
    rows = run_matrix(prompts, backends, backends_cfg, ctx)
    db.finish_run(run_id)

    ok = sum(1 for r in rows if not r["error"])
    err = len(rows) - ok
    console.print(
        f"\n[bold green]done[/bold green]: {ok} ok, {err} failed "
        f"({len(prompts)} prompts x {len(backends)} backends). run_id={run_id}"
    )


@app.command("list")
def list_cmd(
    limit: int = typer.Option(20, "--limit", "-n"),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """List recent runs."""
    db = _db(db_path)
    runs = db.list_runs(limit=limit)
    if not runs:
        console.print("[dim]no runs yet[/dim]")
        return
    table = Table(title=f"Recent runs (latest {limit})")
    table.add_column("ID", justify="right")
    table.add_column("Started")
    table.add_column("Finished")
    table.add_column("Prompt set")
    table.add_column("Backends")
    for r in runs:
        table.add_row(
            str(r["id"]),
            r["started_at"],
            r["finished_at"] or "-",
            r["prompt_set_name"] or "-",
            r["backend_names"],
        )
    console.print(table)


@app.command()
def show(
    run_id: int = typer.Argument(..., help="Run ID to display."),
    mode: str = typer.Option(
        "summary", "--mode", "-m", help="summary | full | diff"
    ),
    other_run: int | None = typer.Option(
        None, "--against", help="For diff mode, second run to diff against."
    ),
    prompt: str | None = typer.Option(
        None, "--prompt", help="Restrict to one prompt id."
    ),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """Show results from a run."""
    db = _db(db_path)
    run_row = db.get_run(run_id)
    if run_row is None:
        raise typer.BadParameter(f"no such run: {run_id}")
    results = db.get_results(run_id)
    if prompt:
        results = [r for r in results if r["prompt_id"] == prompt]

    if mode == "summary":
        summary_table(results, console)
    elif mode == "full":
        side_by_side(results, console)
    elif mode == "diff":
        if other_run is None:
            raise typer.BadParameter("--against is required for --mode diff")
        a = {r["prompt_id"]: r for r in results}
        b_rows = db.get_results(other_run)
        b = {r["prompt_id"]: r for r in b_rows}
        common = set(a) & set(b)
        for pid in sorted(common):
            console.rule(f"[bold cyan]{pid}[/bold cyan]")
            diff_outputs(a[pid], b[pid], console)
    else:
        raise typer.BadParameter(f"unknown mode: {mode}")


@app.command()
def export(
    run_id: int = typer.Argument(..., help="Run ID to export."),
    out: Path = typer.Option(Path("exports/run-{run_id}.md"), "--out", "-o"),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """Export a run to Markdown."""
    db = _db(db_path)
    run_row = db.get_run(run_id)
    if run_row is None:
        raise typer.BadParameter(f"no such run: {run_id}")
    results = db.get_results(run_id)
    final_out = Path(str(out).replace("{run_id}", str(run_id)))
    export_markdown(run_row, results, final_out)
    console.print(f"wrote {final_out}")


@app.command()
def grade(
    run_id: int = typer.Argument(..., help="Run ID to (re-)grade."),
    prompts_file: Path = typer.Option(..., "--prompts", "-p", help="YAML prompt set (source of validators)."),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """(Re-)apply inline validators to every result in a run.

    Useful when you add validators to prompts.yaml after a run already exists.
    Skips results that have no matching prompt in the prompts file, and skips
    results where the model errored.
    """
    db = _db(db_path)
    if db.get_run(run_id) is None:
        raise typer.BadParameter(f"no such run: {run_id}")
    pset = PromptSet.from_yaml(prompts_file)
    validators_by_id = {p.id: p.validators for p in pset.prompts if p.validators}

    results = db.get_results(run_id)
    graded = 0
    skipped = 0
    for r in results:
        vals = validators_by_id.get(r["prompt_id"])
        if not vals:
            skipped += 1
            continue
        if r["error"]:
            skipped += 1
            continue
        report = grade_output(r["output"] or "", vals)
        db.set_validation(r["id"], json.dumps(report))
        graded += 1

    console.print(
        f"[green]graded[/green] {graded} result(s), skipped {skipped} (no validators or errored)"
    )
    console.print(f"[dim]known checks: {', '.join(sorted(KNOWN_CHECKS))}[/dim]")


@app.command()
def tag(
    result_id: int = typer.Argument(..., help="Result row id."),
    tags: list[str] = typer.Argument(..., help="One or more tags to add."),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """Tag a result."""
    db = _db(db_path)
    if db.get_result(result_id) is None:
        raise typer.BadParameter(f"no such result: {result_id}")
    for t in tags:
        db.add_tag(result_id, t)
    console.print(f"tagged result {result_id} with {tags}")


@app.command()
def note(
    result_id: int = typer.Argument(..., help="Result row id."),
    text: str = typer.Argument(..., help="Note text."),
    db_path: Path | None = typer.Option(None, "--db"),
) -> None:
    """Set a free-form note on a result."""
    db = _db(db_path)
    if db.get_result(result_id) is None:
        raise typer.BadParameter(f"no such result: {result_id}")
    db.set_notes(result_id, text)
    console.print(f"note saved on result {result_id}")


@app.command()
def diff(
    a: int = typer.Argument(..., help="First result id."),
    b: int = typer.Argument(..., help="Second result id."),
    db_path: Path | None = typer.Option(None, "--db"),
    context: int = typer.Option(3, "--context", "-c", help="Diff context lines."),
) -> None:
    """Print a colored unified diff between two result outputs."""
    db = _db(db_path)
    ra = db.get_result(a)
    rb = db.get_result(b)
    if ra is None:
        raise typer.BadParameter(f"no such result: {a}")
    if rb is None:
        raise typer.BadParameter(f"no such result: {b}")
    diff_outputs(ra, rb, console, context=context)


@app.command()
def replay(
    run_id: int = typer.Argument(..., help="Original run id to replay."),
    backends_file: Path | None = typer.Option(
        None,
        "--backends",
        "-b",
        help="Override the backends used; by default the run's stored (redacted) snapshot is replayed.",
    ),
    prompts_file: Path | None = typer.Option(
        None, "--prompts", "-p", help="Original prompts file (replay will use real text)."
    ),
    parallel: int = typer.Option(1, "--parallel", "-j"),
    db_path: Path | None = typer.Option(None, "--db"),
    notes: str = typer.Option("", "--notes"),
    api_key: list[str] | None = typer.Option(None, "--api-key"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Replay the prompts of an old run against the same (or new) backends.

    Prompt text is read from the original run's stored `prompts_json` first, so
    a run can be replayed exactly even if the original prompts file has since
    been edited (pass --prompts to override, matched by id). Backends default to
    the run's stored `backends_json` snapshot (secrets redacted; keys resolve
    fresh from the environment); pass --backends to override.
    """
    try:
        overrides = parse_key_override(api_key)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    resolver = build_resolver(overrides=overrides, env_file=env_file)

    db = _db(db_path)
    original = db.get_run(run_id)
    if original is None:
        raise typer.BadParameter(f"no such run: {run_id}")

    prompt_ids = db.get_prompts_for_run(run_id)
    if not prompt_ids:
        raise typer.BadParameter("run has no results")

    stored_prompts_json = original["prompts_json"]
    if stored_prompts_json is None:
        stored_prompts_json = ""
    stored_prompts: list[Prompt] = []
    if stored_prompts_json:
        try:
            stored_prompts = [
                Prompt(id=p["id"], text=p["text"])
                for p in json.loads(stored_prompts_json)
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise typer.BadParameter(f"run {run_id} has malformed prompts_json: {e}") from None

    stored_by_id = {p.id: p for p in stored_prompts}

    stored_backends_json = original["backends_json"]
    if stored_backends_json is None:
        stored_backends_json = ""
    stored_backends: list[BackendConfig] = []
    if stored_backends_json:
        try:
            raw = json.loads(stored_backends_json)
            stored_backends = [_backend_config_from_snapshot(d) for d in raw]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError) as e:
            raise typer.BadParameter(
                f"run {run_id} has malformed backends_json: {e}"
            ) from None

    if prompts_file is not None:
        pset = PromptSet.from_yaml(prompts_file)
        by_id = {p.id: p for p in pset.prompts}
        replay_prompts = [by_id[pid] for pid in prompt_ids if pid in by_id]
        missing = set(prompt_ids) - {p.id for p in replay_prompts}
        if missing:
            raise typer.BadParameter(
                f"prompts file is missing ids from the original run: {sorted(missing)}"
            )
    elif stored_prompts:
        replay_prompts = [stored_by_id[pid] for pid in prompt_ids if pid in stored_by_id]
        missing = set(prompt_ids) - {p.id for p in replay_prompts}
        if missing:
            raise typer.BadParameter(
                f"stored prompts missing ids from run {run_id}: {sorted(missing)}"
            )
    else:
        raise typer.BadParameter(
            f"run {run_id} predates prompt-text storage; pass --prompts with the original file"
        )
    pset = PromptSet(name=f"replay-of-{run_id}", prompts=replay_prompts)

    if backends_file is not None:
        bset = BackendSet.from_yaml(backends_file)
        cfgs = bset.find(None)
    elif stored_backends:
        cfgs = stored_backends
    else:
        raise typer.BadParameter(
            f"run {run_id} predates backends-config storage; "
            "pass --backends with the original file"
        )
    _warn_literal_keys(cfgs)

    new_run_id = db.create_run(
        f"replay-of-{run_id}",
        [c.name for c in cfgs],
        notes=notes or f"replay of run {run_id}",
        prompts=[{"id": p.id, "text": p.text} for p in replay_prompts],
        backends=[redact_backend_config(c) for c in cfgs],
        meta=build_run_meta("replay"),
    )
    backends = [build_backend(c, key_resolver=resolver) for c in cfgs]
    ctx = RunContext(run_id=new_run_id, db=db, parallel=parallel)
    run_matrix(pset.prompts, backends, cfgs, ctx)
    db.finish_run(new_run_id)
    console.print(f"replay run_id={new_run_id}")


@app.command()
def validate(
    prompts_file: Path | None = typer.Option(None, "--prompts", "-p"),
    backends_file: Path | None = typer.Option(None, "--backends", "-b"),
    api_key: list[str] | None = typer.Option(None, "--api-key"),
    env_file: Path | None = typer.Option(None, "--env-file"),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit with a non-zero status if any backend has a missing/unresolved key.",
    ),
) -> None:
    """Validate prompt and/or backend YAML without running anything.

    With --backends, also reports whether each backend's API key resolves
    (and from which source: --api-key, .env file, api_key_env, or api_key
    literal in config). Use --strict in CI to fail when keys are missing.
    """
    try:
        overrides = parse_key_override(api_key)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    resolver = build_resolver(overrides=overrides, env_file=env_file)

    warnings = 0
    if prompts_file:
        ps = PromptSet.from_yaml(prompts_file)
        console.print(f"[green]ok[/green] prompts: {len(ps.prompts)} in set '{ps.name}'")
    if backends_file:
        bs = BackendSet.from_yaml(backends_file)
        for b in bs.backends:
            try:
                build_backend(b, key_resolver=resolver)
            except BackendError as e:
                console.print(f"[red]err[/red] {b.name}: {e}")
                warnings += 1
                continue
            key = resolver.resolve(b)
            source = _key_source(b, resolver)
            literal_warn = literal_key_warning(b)
            if literal_warn:
                console.print(f"[yellow]warn[/yellow] {literal_warn}")
            if key is None and b.type not in ("ollama", "command", "claude_cli", "codex_cli"):
                hint = _missing_key_hint(b)
                msg = f"backend: {b.name} ({b.type}) — no key resolved; {hint}"
                if source:
                    msg = f"backend: {b.name} ({b.type}) — {source} (unresolved); {hint}"
                console.print(f"[yellow]warn[/yellow] {msg}")
                warnings += 1
            else:
                console.print(
                    f"[green]ok[/green] backend: {b.name} ({b.type}) key={_key_status(resolver, b)}"
                )

    if strict and warnings:
        raise typer.Exit(code=1)


def _missing_key_hint(cfg: BackendConfig) -> str:
    """Return a concrete 'set VAR' hint naming the env var the backend wants."""
    if cfg.api_key_env:
        return f"set env var {cfg.api_key_env} (api_key_env) or pass --api-key {cfg.name}=…"
    return (
        f"set api_key or api_key_env on backend {cfg.name}, "
        f"or pass --api-key {cfg.name}=…"
    )


@app.command()
def dashboard(
    db_path: Path | None = typer.Option(None, "--db"),
    host: str = typer.Option("127.0.0.1", "--host", "-h"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start a small web dashboard for browsing runs (FastAPI + HTMX)."""
    from .dashboard import run_dashboard

    db = _db(db_path)
    console.print(f"[bold]dashboard[/bold] serving {db.path} at http://{host}:{port}")
    run_dashboard(db.path, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
