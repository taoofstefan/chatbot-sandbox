"""SQLite storage layer."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_(.+)\.sql$")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_migrations() -> list[tuple[int, str, Path]]:
    """Return [(version, name, path), ...] sorted by version."""
    out: list[tuple[int, str, Path]] = []
    for path in MIGRATIONS_DIR.glob("*.sql"):
        m = _MIGRATION_RE.match(path.name)
        if m:
            out.append((int(m.group(1)), m.group(2), path))
    out.sort()
    return out


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    assert row is not None
    return int(row[0])


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {int(version)}")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


class Database:
    """Thin wrapper over sqlite3 with file-based migrations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            self._bootstrap_and_migrate(conn)

    def _bootstrap_and_migrate(self, conn: sqlite3.Connection) -> None:
        """Apply pending migrations.

        For a database created before the migration system existed, we
        inspect the actual schema and stamp the appropriate starting
        version, then apply anything newer.
        """
        version = _current_version(conn)
        if version == 0 and _table_exists(conn, "runs"):
            if _column_exists(conn, "runs", "prompts_json"):
                _set_version(conn, 2)
            else:
                _set_version(conn, 1)
            version = _current_version(conn)
        for v, _name, path in _load_migrations():
            if v > version:
                sql = path.read_text(encoding="utf-8")
                conn.executescript(sql)
                _set_version(conn, v)
                version = v

    def user_version(self) -> int:
        with self.connect() as conn:
            return _current_version(conn)

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
        prompts: list[dict[str, str]] | None = None,
    ) -> int:
        prompts_json = json.dumps(prompts) if prompts is not None else None
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, prompt_set_name, backend_names, notes, prompts_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (now_iso(), prompt_set_name, ",".join(backend_names), notes, prompts_json),
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

    def set_run_notes(self, run_id: int, notes: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE runs SET notes = ? WHERE id = ?", (notes, run_id))

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

    def get_tags_for_result(self, result_id: int) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM tags WHERE result_id = ? ORDER BY tag",
                (result_id,),
            ).fetchall()
        return [r["tag"] for r in rows]
