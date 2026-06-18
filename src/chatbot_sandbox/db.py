"""SQLite storage layer."""

from __future__ import annotations

import json
import platform
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_RE = re.compile(r"^(\d{4})_(.+)\.sql$")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_run_meta(command: str) -> dict[str, str]:
    """Build the run-metadata snapshot stored in ``runs.meta_json``.

    Captures the tool version, the invoking command, and the Python/platform
    that produced the run — enough to audit *how* a run was made without
    storing anything secret. The full argv is intentionally excluded so a key
    passed via ``--api-key backend=value`` can never leak into the database.
    """
    return {
        "cbs_version": __version__,
        "command": command,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


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
                self._apply_migration(conn, v, sql)
                _set_version(conn, v)
                version = v

    def _apply_migration(self, conn: sqlite3.Connection, version: int, sql: str) -> None:
        """Apply one migration, with per-version guards for legacy schemas."""
        if version == 3:
            # 0003 adds results.validation_json. Skip the ALTER TABLE on a
            # database that pre-dates the results table (e.g. legacy v1 DBs
            # that only have the runs table).
            if _table_exists(conn, "results"):
                if not _column_exists(conn, "results", "validation_json"):
                    conn.execute("ALTER TABLE results ADD COLUMN validation_json TEXT")
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_results_validation "
                    "ON results(run_id, prompt_id)"
                )
            return
        conn.executescript(sql)

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
        backends: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> int:
        prompts_json = json.dumps(prompts) if prompts is not None else None
        backends_json = json.dumps(backends) if backends is not None else None
        meta_json = json.dumps(meta) if meta is not None else None
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, prompt_set_name, backend_names, notes, "
                "prompts_json, backends_json, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    now_iso(),
                    prompt_set_name,
                    ",".join(backend_names),
                    notes,
                    prompts_json,
                    backends_json,
                    meta_json,
                ),
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
                    started_at, tags, notes, validation_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    result.get("validation_json"),
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def set_validation(self, result_id: int, validation_json: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE results SET validation_json = ? WHERE id = ?",
                (validation_json, result_id),
            )

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

    # ------------------------------------------------------------------
    # Agentic-run persistence (migration 0004)
    # ------------------------------------------------------------------

    def create_agent_run(
        self,
        run_id: int,
        prompt_id: str,
        backend_name: str,
        *,
        final_answer: str | None = None,
        total_steps: int = 0,
        completed_normally: bool = False,
        started_at: str | None = None,
        finished_at: str | None = None,
        final_messages_json: str | None = None,
    ) -> int:
        """Insert a new agent_runs row. Returns the new id."""
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_runs (
                    run_id, prompt_id, backend_name, final_answer,
                    total_steps, completed_normally,
                    started_at, finished_at, final_messages_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    prompt_id,
                    backend_name,
                    final_answer,
                    total_steps,
                    1 if completed_normally else 0,
                    started_at or now_iso(),
                    finished_at,
                    final_messages_json,
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def finish_agent_run(
        self,
        agent_run_id: int,
        *,
        final_answer: str | None,
        total_steps: int,
        completed_normally: bool,
        final_messages_json: str | None = None,
    ) -> None:
        """Update an agent_runs row at the end of a run."""
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs SET
                    final_answer = ?,
                    total_steps = ?,
                    completed_normally = ?,
                    finished_at = ?,
                    final_messages_json = COALESCE(?, final_messages_json)
                WHERE id = ?
                """,
                (
                    final_answer,
                    total_steps,
                    1 if completed_normally else 0,
                    now_iso(),
                    final_messages_json,
                    agent_run_id,
                ),
            )

    def insert_tool_call(
        self,
        agent_run_id: int,
        step_index: int,
        tool_name: str,
        arguments: Mapping[str, object],
        result: Mapping[str, object],
        *,
        ok: bool,
        error: str | None,
        duration_ms: int,
    ) -> int:
        """Insert one tool_calls row. Returns the new id."""
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tool_calls (
                    agent_run_id, step_index, tool_name,
                    arguments_json, result_json,
                    ok, error, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_run_id,
                    step_index,
                    tool_name,
                    json.dumps(dict(arguments), default=str),
                    json.dumps(dict(result), default=str),
                    1 if ok else 0,
                    error,
                    duration_ms,
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def insert_judge_score(
        self,
        agent_run_id: int,
        rubric: str,
        judge_backend: str,
        score: int,
        *,
        judge_model: str | None = None,
        evidence: str | None = None,
        raw_response: str | None = None,
        latency_ms: int = 0,
    ) -> int:
        """Insert one judge_scores row. Returns the new id."""
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO judge_scores (
                    agent_run_id, rubric, judge_backend, judge_model,
                    score, evidence, raw_response, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_run_id,
                    rubric,
                    judge_backend,
                    judge_model,
                    score,
                    evidence,
                    raw_response,
                    latency_ms,
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_agent_run(self, agent_run_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(  # type: ignore[no-any-return]
                "SELECT * FROM agent_runs WHERE id = ?", (agent_run_id,)
            ).fetchone()

    def list_agent_runs_for_run(self, run_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM agent_runs WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()

    def get_tool_calls_for_agent_run(self, agent_run_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM tool_calls WHERE agent_run_id = ? ORDER BY step_index, id",
                (agent_run_id,),
            ).fetchall()

    def get_judge_scores_for_agent_run(self, agent_run_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM judge_scores WHERE agent_run_id = ? ORDER BY rubric, id",
                (agent_run_id,),
            ).fetchall()

    def clear_judge_scores(self, agent_run_id: int) -> int:
        """Delete all judge_scores rows for an agent run.

        ``judge_scores`` has no uniqueness constraint, so re-judging the same
        agent run would otherwise append duplicate rows and skew the medians.
        Returns the number of rows deleted.
        """
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM judge_scores WHERE agent_run_id = ?",
                (agent_run_id,),
            )
            return cur.rowcount or 0

    def get_agent_run_for_result(self, result_id: int) -> sqlite3.Row | None:
        """Find the agent_runs row whose prompt_id/backend matches this result."""
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
            if r is None:
                return None
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id = ? AND prompt_id = ? AND backend_name = ? "
                "ORDER BY id DESC LIMIT 1",
                (r["run_id"], r["prompt_id"], r["backend_name"]),
            ).fetchone()
            return row  # type: ignore[no-any-return]
