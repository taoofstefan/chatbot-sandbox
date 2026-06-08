"""Typer CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from . import __version__
from .backends import build_backend, known_types
from .backends.base import Backend, BackendError
from .compare import diff_outputs, side_by_side, summary_table
from .config import BackendConfig, BackendSet, Prompt, PromptSet
from .db import Database
from .export import export_markdown
from .runner import RunContext, run_matrix
from .secrets import KeyResolver, build_resolver, parse_key_override

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


@app.command()
def version() -> None:
    """Print version."""
    console.print(f"chatbot-sandbox {__version__}")


@app.command()
def types() -> None:
    """List known backend types."""
    console.print(", ".join(known_types()))


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

    if dry_run:
        console.print("[yellow]dry-run: not executing[/yellow]")
        return

    db = _db(db_path)
    run_id = db.create_run(
        pset.name,
        [b.name for b in backends_cfg],
        notes=notes,
        prompts=[{"id": p.id, "text": p.text} for p in prompts],
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
def replay(
    run_id: int = typer.Argument(..., help="Original run id to replay."),
    backends_file: Path = typer.Option(..., "--backends", "-b"),
    prompts_file: Path | None = typer.Option(
        None, "--prompts", "-p", help="Original prompts file (replay will use real text)."
    ),
    parallel: int = typer.Option(1, "--parallel", "-j"),
    db_path: Path | None = typer.Option(None, "--db"),
    notes: str = typer.Option("", "--notes"),
    api_key: list[str] | None = typer.Option(None, "--api-key"),
    env_file: Path | None = typer.Option(None, "--env-file"),
) -> None:
    """Replay the prompts of an old run against (possibly new) backends.

    Prompt text is read from the original run's stored `prompts_json` first,
    so a run can be replayed exactly even if the original prompts file has
    since been edited. Pass --prompts to override (matched by id).
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
    bset = BackendSet.from_yaml(backends_file)
    cfgs = bset.find(None)

    new_run_id = db.create_run(
        f"replay-of-{run_id}",
        [c.name for c in cfgs],
        notes=notes or f"replay of run {run_id}",
        prompts=[{"id": p.id, "text": p.text} for p in replay_prompts],
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
) -> None:
    """Validate prompt and/or backend YAML without running anything.

    With --backends, also reports whether each backend's API key resolves
    (and from which source: --api-key, .env file, api_key_env, or api_key
    literal in config).
    """
    try:
        overrides = parse_key_override(api_key)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    resolver = build_resolver(overrides=overrides, env_file=env_file)

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
                continue
            key = resolver.resolve(b)
            source = _key_source(b, resolver)
            if key is None and b.type not in ("ollama", "command", "claude_cli", "codex_cli"):
                console.print(
                    f"[yellow]warn[/yellow] backend: {b.name} ({b.type}) — no key resolved; "
                    f"{source or 'set api_key or api_key_env'}"
                )
            else:
                console.print(
                    f"[green]ok[/green] backend: {b.name} ({b.type}) key={_key_status(resolver, b)}"
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
