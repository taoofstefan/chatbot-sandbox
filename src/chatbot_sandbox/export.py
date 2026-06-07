"""Export run results to Markdown."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def export_markdown(run: sqlite3.Row, results: list[sqlite3.Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# Run #{run['id']} — {run['prompt_set_name'] or '(no prompt set)'}")
    lines.append("")
    lines.append(f"- Started:  `{run['started_at']}`")
    if run["finished_at"]:
        lines.append(f"- Finished: `{run['finished_at']}`")
    lines.append(f"- Backends: `{run['backend_names']}`")
    if run["notes"]:
        lines.append(f"- Notes: {run['notes']}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Prompt | Backend | Status | Latency | In | Out | Cost |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        status = "ERR" if r["error"] else "OK"
        in_t = r["input_tokens"] if r["input_tokens"] is not None else "-"
        out_t = r["output_tokens"] if r["output_tokens"] is not None else "-"
        cost = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "-"
        lines.append(
            f"| {r['prompt_id']} | {r['backend_name']} | {status} | "
            f"{r['latency_ms']}ms | {in_t} | {out_t} | {cost} |"
        )
    lines.append("")

    by_prompt: dict[str, list[sqlite3.Row]] = {}
    for r in results:
        by_prompt.setdefault(r["prompt_id"], []).append(r)

    for prompt_id, rows in by_prompt.items():
        lines.append(f"## {prompt_id}")
        lines.append("")
        for r in rows:
            lines.append(f"### {r['backend_name']}")
            lines.append("")
            meta = [f"`{r['latency_ms']}ms`"]
            if r["model"]:
                meta.append(f"model: `{r['model']}`")
            if r["input_tokens"] is not None:
                meta.append(f"tokens: {r['input_tokens']}+{r['output_tokens']}")
            if r["cost_usd"] is not None:
                meta.append(f"cost: ${r['cost_usd']:.4f}")
            lines.append("  ".join(meta))
            lines.append("")
            if r["error"]:
                lines.append(f"> **ERROR**: {r['error']}")
            else:
                lines.append("```")
                lines.append((r["output"] or "").rstrip())
                lines.append("```")
            if r["notes"]:
                lines.append("")
                lines.append(f"_Notes: {r['notes']}_")
            if r["tags"]:
                lines.append("")
                lines.append("Tags: " + " ".join(f"`{t}`" for t in r["tags"].split(",") if t))
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
