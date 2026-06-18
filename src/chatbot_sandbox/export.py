"""Export run results to Markdown."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _validation_md(row: sqlite3.Row) -> list[str]:
    raw = row["validation_json"]
    if not raw:
        return []
    try:
        report = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not report:
        return []
    lines = ["", "**Validation:**"]
    for name, info in report.items():
        mark = "✅" if info.get("passed") else "❌"
        lines.append(f"- {mark} `{name}` — {info.get('detail', '')}")
    return lines


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
    lines.append("| Prompt | Backend | Status | Latency | In | Out | Cost | Val |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        status = "ERR" if r["error"] else "OK"
        in_t = r["input_tokens"] if r["input_tokens"] is not None else "-"
        out_t = r["output_tokens"] if r["output_tokens"] is not None else "-"
        cost = f"${r['cost_usd']:.4f}" if r["cost_usd"] is not None else "-"
        val = "-"
        if r["validation_json"]:
            try:
                report = json.loads(r["validation_json"])
                if report:
                    passed = sum(1 for c in report.values() if c.get("passed"))
                    val = f"{passed}/{len(report)}"
            except (ValueError, TypeError):
                pass
        lines.append(
            f"| {r['prompt_id']} | {r['backend_name']} | {status} | "
            f"{r['latency_ms']}ms | {in_t} | {out_t} | {cost} | {val} |"
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
            lines.extend(_validation_md(r))
            if r["notes"]:
                lines.append("")
                lines.append(f"_Notes: {r['notes']}_")
            if r["tags"]:
                lines.append("")
                lines.append("Tags: " + " ".join(f"`{t}`" for t in r["tags"].split(",") if t))
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


_AGENT_AXES = ("planning", "recovery", "honesty", "minimality", "safety")


def export_agent_leaderboard(
    run: sqlite3.Row,
    rows: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write an agentic-run leaderboard to Markdown.

    `rows` is the structured per-backend summary from `Database.agent_leaderboard`
    (each has ``backend``, ``cases``, ``auto_passed``, and ``medians`` keyed by
    the 5 judge axes). One table row per backend.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append(f"# Agent leaderboard — run #{run['id']}")
    lines.append("")
    lines.append(f"- Prompt set: `{run['prompt_set_name'] or '-'}`")
    lines.append(f"- Backends: `{run['backend_names']}`")
    if run["notes"]:
        lines.append(f"- Notes: {run['notes']}")
    lines.append("")

    lines.append("## Leaderboard")
    lines.append("")
    header = "| Backend | Cases | Auto pass | " + " | ".join(_AGENT_AXES) + " |"
    sep = "|---|---:|---:|" + "|".join(["---:"] * len(_AGENT_AXES)) + "|"
    lines.append(header)
    lines.append(sep)
    for r in rows:
        medians = r.get("medians", {})
        cells = [
            str(r["backend"]),
            str(r["cases"]),
            f"{r['auto_passed']}/{r['cases']}",
        ]
        for axis in _AGENT_AXES:
            m = medians.get(axis, 0.0)
            cells.append(f"{float(m):.1f}" if m else "-")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
