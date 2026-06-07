"""Side-by-side comparison and diff of results from a run."""

from __future__ import annotations

import difflib
import sqlite3

from rich.console import Console
from rich.table import Table


def summary_table(results: list[sqlite3.Row], console: Console) -> None:
    table = Table(title="Run summary", show_lines=False)
    table.add_column("Prompt", style="cyan")
    table.add_column("Backend", style="magenta")
    table.add_column("Status")
    table.add_column("Latency", justify="right")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Cost", justify="right")

    for r in results:
        status = "[red]ERR[/red]" if r["error"] else "[green]OK[/green]"
        in_t = str(r["input_tokens"]) if r["input_tokens"] is not None else "-"
        out_t = str(r["output_tokens"]) if r["output_tokens"] is not None else "-"
        cost = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "-"
        table.add_row(
            r["prompt_id"],
            r["backend_name"],
            status,
            f"{r['latency_ms']}ms",
            in_t,
            out_t,
            cost,
        )
    console.print(table)


def side_by_side(results: list[sqlite3.Row], console: Console, max_width: int = 80) -> None:
    """Print every prompt's outputs, one block per backend."""
    by_prompt: dict[str, list[sqlite3.Row]] = {}
    for r in results:
        by_prompt.setdefault(r["prompt_id"], []).append(r)

    for prompt_id, rows in by_prompt.items():
        console.rule(f"[bold cyan]{prompt_id}[/bold cyan]")
        for r in rows:
            header = f"[bold magenta]{r['backend_name']}[/bold magenta]"
            if r["error"]:
                console.print(f"{header}  [red]ERROR[/red]  {r['error']}")
            else:
                console.print(
                    f"{header}  ({r['latency_ms']}ms"
                    + (f", {r['input_tokens']}+{r['output_tokens']} tok" if r["input_tokens"] else "")
                    + ")"
                )
                out = r["output"] or ""
                if len(out) > 2000:
                    out = out[:2000] + "\n... [truncated]"
                console.print(out)
        console.print()


def diff_outputs(
    a: sqlite3.Row,
    b: sqlite3.Row,
    console: Console,
    context: int = 3,
) -> None:
    a_text = a["output"] or ""
    b_text = b["output"] or ""
    diff = difflib.unified_diff(
        a_text.splitlines(),
        b_text.splitlines(),
        fromfile=f"{a['backend_name']} ({a['prompt_id']})",
        tofile=f"{b['backend_name']} ({b['prompt_id']})",
        n=context,
        lineterm="",
    )
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            console.print(line, style="green")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(line, style="red")
        elif line.startswith("@@"):
            console.print(line, style="cyan")
        else:
            console.print(line)
