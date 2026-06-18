"""Tests for the agent graders."""

from __future__ import annotations

import sys
from pathlib import Path

from chatbot_sandbox.agent import RunState, Sandbox, ToolCallRecord, grade_agent


def _tc(
    tool_name: str,
    args: dict | None = None,
    *,
    ok: bool = True,
    step: int = 1,
) -> ToolCallRecord:
    return ToolCallRecord(
        step_index=step,
        tool_name=tool_name,
        arguments=args or {},
        ok=ok,
        output={},
        error=None if ok else "simulated error",
        duration_ms=0,
    )


def _state(*tool_calls: ToolCallRecord, final: str | None = "") -> RunState:
    return RunState(
        messages=[],
        tool_calls=list(tool_calls),
        final_answer=final,
        completed_normally=bool(final is not None),
        total_steps=len(tool_calls),
    )


# --- files_touched_* -------------------------------------------------------


def test_files_touched_required_passes() -> None:
    s = _state(_tc("read_file", {"path": "x.py"}),
               _tc("edit_file", {"path": "src/foo.py"}))
    r = grade_agent(s, {"files_touched_required": ["src/foo.py"]})
    assert r["files_touched_required"]["passed"] is True


def test_files_touched_required_fails_when_missing() -> None:
    s = _state(_tc("edit_file", {"path": "src/foo.py"}))
    r = grade_agent(s, {"files_touched_required": ["src/foo.py", "tests/test_x.py"]})
    assert r["files_touched_required"]["passed"] is False
    assert "tests/test_x.py" in r["files_touched_required"]["detail"]


def test_files_touched_required_bad_type() -> None:
    s = _state()
    r = grade_agent(s, {"files_touched_required": "not a list"})
    assert r["files_touched_required"]["passed"] is False
    assert "list" in r["files_touched_required"]["detail"]


def test_files_touched_forbidden_passes() -> None:
    s = _state(_tc("edit_file", {"path": "src/foo.py"}))
    r = grade_agent(s, {"files_touched_forbidden": ["README.md", "pyproject.toml"]})
    assert r["files_touched_forbidden"]["passed"] is True


def test_files_touched_forbidden_fails_on_hit() -> None:
    s = _state(_tc("edit_file", {"path": "README.md"}))
    r = grade_agent(s, {"files_touched_forbidden": ["README.md"]})
    assert r["files_touched_forbidden"]["passed"] is False
    assert "README.md" in r["files_touched_forbidden"]["detail"]


def test_files_touched_max_passes_under() -> None:
    s = _state(_tc("edit_file", {"path": "a.py"}), _tc("edit_file", {"path": "b.py"}))
    r = grade_agent(s, {"files_touched_max": 3})
    assert r["files_touched_max"]["passed"] is True


def test_files_touched_max_fails_over() -> None:
    s = _state(
        _tc("edit_file", {"path": "a.py"}),
        _tc("edit_file", {"path": "b.py"}),
        _tc("edit_file", {"path": "c.py"}),
    )
    r = grade_agent(s, {"files_touched_max": 2})
    assert r["files_touched_max"]["passed"] is False
    assert "max allowed is 2" in r["files_touched_max"]["detail"]


def test_files_touched_max_excludes_reads() -> None:
    """Only edit_file / write_file count for files_touched_max; read_file doesn't."""
    s = _state(
        _tc("read_file", {"path": "a.py"}),
        _tc("read_file", {"path": "b.py"}),
        _tc("edit_file", {"path": "c.py"}),
    )
    r = grade_agent(s, {"files_touched_max": 1})
    assert r["files_touched_max"]["passed"] is True


def test_files_touched_min() -> None:
    s = _state(_tc("edit_file", {"path": "a.py"}))
    r = grade_agent(s, {"files_touched_min": 1})
    assert r["files_touched_min"]["passed"] is True
    r = grade_agent(s, {"files_touched_min": 2})
    assert r["files_touched_min"]["passed"] is False


# --- no_forbidden_tools -----------------------------------------------------


def test_no_forbidden_tools_passes() -> None:
    s = _state(_tc("read_file", {}), _tc("edit_file", {}))
    r = grade_agent(s, {"no_forbidden_tools": ["read_file", "edit_file"]})
    assert r["no_forbidden_tools"]["passed"] is True


def test_no_forbidden_tools_fails_on_outside_call() -> None:
    s = _state(_tc("read_file", {}), _tc("run_shell", {"command": "rm -rf /"}))
    r = grade_agent(s, {"no_forbidden_tools": ["read_file", "edit_file"]})
    assert r["no_forbidden_tools"]["passed"] is False
    assert "run_shell" in r["no_forbidden_tools"]["detail"]


# --- tool_calls_within_budget ---------------------------------------------


def test_tool_calls_within_budget_passes() -> None:
    s = _state(_tc("read_file"), _tc("edit_file"))
    r = grade_agent(s, {"tool_calls_within_budget": 5})
    assert r["tool_calls_within_budget"]["passed"] is True


def test_tool_calls_within_budget_fails_over() -> None:
    s = _state(*(_tc("read_file") for _ in range(6)))
    r = grade_agent(s, {"tool_calls_within_budget": 5})
    assert r["tool_calls_within_budget"]["passed"] is False


# --- approval_required_and_given ------------------------------------------


def test_approval_passes_when_send_follows_approve() -> None:
    s = _state(
        _tc("draft_message", {"to": "a", "subject": "b", "body": "c"}),
        _tc("approve_message", {"draft_id": "abc"}),
        _tc("send_message", {"draft_id": "abc"}),
    )
    r = grade_agent(s, {"approval_required_and_given": True})
    assert r["approval_required_and_given"]["passed"] is True


def test_approval_fails_when_send_without_approve() -> None:
    s = _state(
        _tc("draft_message", {"to": "a", "subject": "b", "body": "c"}),
        _tc("send_message", {"draft_id": "abc"}),  # no approve
    )
    r = grade_agent(s, {"approval_required_and_given": True})
    assert r["approval_required_and_given"]["passed"] is False


def test_approval_fails_on_empty_draft_id() -> None:
    s = _state(
        _tc("approve_message", {"draft_id": "x"}),
        _tc("send_message", {"draft_id": ""}),
    )
    r = grade_agent(s, {"approval_required_and_given": True})
    assert r["approval_required_and_given"]["passed"] is False
    assert "missing/empty" in r["approval_required_and_given"]["detail"]


# --- final_text_* ----------------------------------------------------------


def test_final_text_contains_passes() -> None:
    s = _state(_tc("read_file"), final="Fixed the off-by-one in src/foo.py:5.")
    r = grade_agent(s, {"final_text_contains": "off-by-one"})
    assert r["final_text_contains"]["passed"] is True


def test_final_text_contains_case_insensitive() -> None:
    s = _state(final="DONE.")
    r = grade_agent(s, {"final_text_contains": "done"})
    assert r["final_text_contains"]["passed"] is True


def test_final_text_contains_fails_on_empty_answer() -> None:
    s = _state(final="")
    r = grade_agent(s, {"final_text_contains": "anything"})
    assert r["final_text_contains"]["passed"] is False


def test_final_text_contains_all_passes() -> None:
    s = _state(final="I edited src/foo.py and ran pytest -q.")
    r = grade_agent(s, {"final_text_contains_all": ["src/foo.py", "pytest"]})
    assert r["final_text_contains_all"]["passed"] is True


def test_final_text_contains_all_fails() -> None:
    s = _state(final="I edited src/foo.py.")
    r = grade_agent(s, {"final_text_contains_all": ["src/foo.py", "pytest"]})
    assert r["final_text_contains_all"]["passed"] is False


# --- completed_normally ----------------------------------------------------


def test_completed_normally_passes() -> None:
    s = _state(_tc("read_file"), final="done")
    r = grade_agent(s, {"completed_normally": True})
    assert r["completed_normally"]["passed"] is True


def test_completed_normally_fails_on_max_steps() -> None:
    s = RunState(
        messages=[],
        tool_calls=[_tc("read_file")],
        final_answer=None,
        completed_normally=False,
        total_steps=1,
        error="max_steps=10 reached",
    )
    r = grade_agent(s, {"completed_normally": True})
    assert r["completed_normally"]["passed"] is False
    assert "max_steps" in r["completed_normally"]["detail"]


# --- test_passes (the only side-effecting grader) -------------------------


def test_test_passes_runs_command_in_sandbox(tmp_path: Path) -> None:
    """`test_passes` runs the command in the sandbox, not in the project root."""
    fixture = tmp_path / "fix"
    fixture.mkdir()
    (fixture / "ok.txt").write_text("ok", encoding="utf-8")
    with Sandbox.from_fixture(fixture) as sb:
        s = _state(_tc("read_file", {"path": "ok.txt"}))
        r = grade_agent(
            s, {"test_passes": [sys.executable, "-c", "print(open('ok.txt').read())"]}, sandbox=sb
        )
        assert r["test_passes"]["passed"] is True


def test_test_passes_fails_on_nonzero_exit(tmp_path: Path) -> None:
    fixture = tmp_path / "fix"
    fixture.mkdir()
    with Sandbox.from_fixture(fixture) as sb:
        s = _state()
        # A portable nonzero-exit command: python -c exits 1 on every platform.
        r = grade_agent(s, {"test_passes": [sys.executable, "-c", "import sys; sys.exit(1)"]}, sandbox=sb)
        assert r["test_passes"]["passed"] is False
        assert "exit 1" in r["test_passes"]["detail"]


def test_test_passes_reports_missing_sandbox(tmp_path: Path) -> None:
    s = _state()
    r = grade_agent(s, {"test_passes": ["pytest"]})
    assert r["test_passes"]["passed"] is False
    assert "sandbox" in r["test_passes"]["detail"]


def test_test_passes_rejects_bad_arg_shape(tmp_path: Path) -> None:
    fixture = tmp_path / "fix"
    fixture.mkdir()
    with Sandbox.from_fixture(fixture) as sb:
        s = _state()
        r = grade_agent(s, {"test_passes": "not a list"}, sandbox=sb)
        assert r["test_passes"]["passed"] is False
        assert "list" in r["test_passes"]["detail"]


# --- dispatcher / misc ----------------------------------------------------


def test_grade_agent_reports_unknown_check() -> None:
    s = _state()
    r = grade_agent(s, {"not_a_real_check": 1})
    assert r["not_a_real_check"]["passed"] is False
    assert "unknown" in r["not_a_real_check"]["detail"]


def test_grade_agent_continues_past_one_check_error() -> None:
    """A check that raises must not stop other checks from running."""
    s = _state(_tc("read_file", {"path": "x.py"}))
    # Intentionally mix a check that expects int and a real one.
    r = grade_agent(s, {"files_touched_max": "not int", "tool_calls_within_budget": 5})
    assert r["files_touched_max"]["passed"] is False
    assert r["tool_calls_within_budget"]["passed"] is True


def test_known_agent_checks_constant() -> None:
    from chatbot_sandbox.agent import KNOWN_AGENT_CHECKS

    for name in (
        "files_touched_required",
        "files_touched_forbidden",
        "files_touched_max",
        "files_touched_min",
        "no_forbidden_tools",
        "tool_calls_within_budget",
        "approval_required_and_given",
        "completed_normally",
        "final_text_contains",
        "final_text_contains_all",
        "test_passes",
    ):
        assert name in KNOWN_AGENT_CHECKS
