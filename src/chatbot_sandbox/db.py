"""SQLite storage layer."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    prompt_set_name TEXT,
    backend_names TEXT NOT NULL,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    prompt_id TEXT NOT NULL,
    backend_name TEXT NOT NULL,
    model TEXT,
    output TEXT,
    error TEXT,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    started_at TEXT NOT NULL,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_prompt ON results(prompt_id);
CREATE INDEX IF NOT EXISTS idx_results_backend ON results(backend_name);

CREATE TABLE IF NOT EXISTS tags (
    result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (result_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """Thin wrapper over sqlite3 with the schema above."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        finally:
            conn.close()

    def create_run(
        self,
        prompt_set_name: str | None,
        backend_names: list[str],
        notes: str = "",
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, prompt_set_name, backend_names, notes) "
                "VALUES (?, ?, ?, ?)",
                (now_iso(), prompt_set_name, ",".join(backend_names), notes),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def finish_run(self, run_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ? WHERE id = ?",
                (now_iso(), run_id),
            )

    def insert_result(self, result: dict[str, Any]) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO results (
                    run_id, prompt_id, backend_name, model, output, error,
                    latency_ms, input_tokens, output_tokens, cost_usd,
                    started_at, tags, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["run_id"],
                    result["prompt_id"],
                    result["backend_name"],
                    result.get("model"),
                    result.get("output"),
                    result.get("error"),
                    result.get("latency_ms"),
                    result.get("input_tokens"),
                    result.get("output_tokens"),
                    result.get("cost_usd"),
                    result.get("started_at", now_iso()),
                    ",".join(result.get("tags", [])),
                    result.get("notes", ""),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def add_tag(self, result_id: int, tag: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags (result_id, tag) VALUES (?, ?)",
                (result_id, tag),
            )

    def set_notes(self, result_id: int, notes: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE results SET notes = ? WHERE id = ?", (notes, result_id))

    def get_run(self, run_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(  # type: ignore[no-any-return]
                "SELECT * FROM runs WHERE id = ?", (run_id,)
            ).fetchone()

    def list_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_results(self, run_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM results WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()

    def get_result(self, result_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(  # type: ignore[no-any-return]
                "SELECT * FROM results WHERE id = ?", (result_id,)
            ).fetchone()

    def get_prompts_for_run(self, run_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT prompt_id FROM results WHERE run_id = ? ORDER BY prompt_id",
                (run_id,),
            ).fetchall()
        return [r["prompt_id"] for r in rows]
