"""Tests for the LLM-judge system."""

from __future__ import annotations

import json
from typing import Any

from chatbot_sandbox.agent import (
    JudgeReport,
    RunState,
    ToolCallRecord,
    judge_panel,
    judge_run,
    parse_judge_response,
    render_audit_for_judge,
)
from chatbot_sandbox.backends.base import ChatResponse


def _tc(
    tool_name: str,
    args: dict | None = None,
    *,
    ok: bool = True,
    step: int = 1,
    output: dict | None = None,
    error: str | None = None,
) -> ToolCallRecord:
    return ToolCallRecord(
        step_index=step,
        tool_name=tool_name,
        arguments=args or {},
        ok=ok,
        output=output or {},
        error=error,
        duration_ms=10,
    )


def _state(*tool_calls: ToolCallRecord, final: str | None = "") -> RunState:
    return RunState(
        messages=[],
        tool_calls=list(tool_calls),
        final_answer=final,
        completed_normally=bool(final),
        total_steps=len(tool_calls),
    )


# --- Audit-trail renderer --------------------------------------------------


def test_render_audit_includes_prompt_and_final_answer() -> None:
    s = _state(_tc("read_file", {"path": "x.py"}), final="all done")
    blob = render_audit_for_judge(s, user_prompt="read x.py")
    assert blob["user_prompt"] == "read x.py"
    assert blob["final_answer"] == "all done"
    assert blob["completed_normally"] is True


def test_render_audit_truncates_long_stdout() -> None:
    long = "x" * 5000
    s = _state(
        _tc("run_shell", {"command": "echo big"}, output={"exit_code": 0, "stdout": long, "stderr": ""})
    )
    blob = render_audit_for_judge(s)
    out = blob["tool_calls"][0]["output"]
    assert out["stdout"].endswith("…[truncated]")
    assert len(out["stdout"]) < 5000


def test_render_audit_truncates_long_content() -> None:
    s = _state(_tc("read_file", {"path": "x.py"}, output={"content": "y" * 5000, "lines": 9999}))
    blob = render_audit_for_judge(s)
    assert blob["tool_calls"][0]["output"]["content"].endswith("…[truncated]")


def test_render_audit_truncates_long_error() -> None:
    s = _state(_tc("read_file", error="e" * 1000))
    blob = render_audit_for_judge(s)
    assert blob["tool_calls"][0]["error"].endswith("…[truncated]")


def test_render_audit_no_prompt() -> None:
    s = _state(_tc("read_file"))
    blob = render_audit_for_judge(s)  # no user_prompt kwarg
    assert blob["user_prompt"] is None


# --- Parser ----------------------------------------------------------------


def test_parse_bare_json() -> None:
    raw = '{"scores": {"planning": 4, "recovery": 3, "honesty": 5, "minimality": 4, "safety": 5}, "evidence": {}}'
    r = parse_judge_response(raw)
    assert r["scores"]["planning"] == 4
    assert r["scores"]["honesty"] == 5


def test_parse_fenced_json() -> None:
    raw = (
        "Sure! Here's my evaluation:\n"
        "```json\n"
        '{"scores": {"planning": 5, "recovery": 5, "honesty": 5, "minimality": 5, "safety": 5}, '
        '"evidence": {}}\n'
        "```\n"
        "Done."
    )
    r = parse_judge_response(raw)
    assert r["scores"]["planning"] == 5


def test_parse_embedded_json_object() -> None:
    raw = (
        "I think the scores are: "
        '{"scores": {"planning": 3, "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3}, "evidence": {}}'
        " overall."
    )
    r = parse_judge_response(raw)
    assert r["scores"]["planning"] == 3


def test_parse_missing_axis_returns_default_low() -> None:
    raw = '{"scores": {"planning": 4}}'  # missing axes
    r = parse_judge_response(raw)
    # Default-low: every axis becomes 1, evidence carries the error.
    assert r["scores"]["planning"] == 1
    assert r["scores"]["recovery"] == 1
    # Some evidence string is set; exact wording depends on which axis was checked first.
    assert r["evidence"]["planning"]
    assert r["evidence"]["recovery"]


def test_parse_out_of_range_returns_default_low() -> None:
    raw = '{"scores": {"planning": 7, "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3}}'
    r = parse_judge_response(raw)
    assert r["scores"]["planning"] == 1
    assert "out of range" in r["evidence"]["planning"]


def test_parse_non_int_score_returns_default_low() -> None:
    raw = '{"scores": {"planning": "four", "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3}}'
    r = parse_judge_response(raw)
    assert r["scores"]["planning"] == 1


def test_parse_garbage_returns_default_low() -> None:
    r = parse_judge_response("I don't feel like scoring today.")
    assert all(v == 1 for v in r["scores"].values())
    assert "could not parse" in r["evidence"]["planning"]


def test_parse_empty_returns_default_low() -> None:
    r = parse_judge_response("")
    assert all(v == 1 for v in r["scores"].values())


def test_parse_accepts_string_evidence() -> None:
    raw = (
        '{"scores": {"planning": 4, "recovery": 4, "honesty": 4, "minimality": 4, "safety": 4},'
        ' "evidence": {"planning": "good", "recovery": 4}}'  # mixed types
    )
    r = parse_judge_response(raw)
    assert r["evidence"]["planning"] == "good"
    assert r["evidence"]["recovery"] == "4"


# --- judge_run (no real model) ---------------------------------------------


class ScriptedChat:
    """Returns a fixed response for the judge's chat call."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[Any] = []

    def __call__(self, messages, tools):
        self.calls.append((list(messages), tools))
        return ChatResponse(content=self.content, tool_calls=[], raw={})


def test_judge_run_parses_valid_response() -> None:
    chat = ScriptedChat(
        '{"scores": {"planning": 5, "recovery": 4, "honesty": 5, "minimality": 5, "safety": 5},'
        ' "evidence": {"planning": "explored first"}}'
    )
    s = _state(_tc("read_file", {"path": "x.py"}), final="done")
    r = judge_run(state=s, chat=chat, user_prompt="read x.py", model_label="judge-x")
    assert r.scores()["planning"] == 5
    assert r.scores()["honesty"] == 5
    assert r.evidence()["planning"] == "explored first"
    assert r.model == "judge-x"
    assert r.error is None


def test_judge_run_records_call_metadata() -> None:
    chat = ScriptedChat('{"scores": {"planning": 3, "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3}}')
    s = _state(_tc("read_file"), final="x")
    r = judge_run(state=s, chat=chat, user_prompt="x")
    assert r.latency_ms >= 0
    assert r.raw  # raw response captured
    # The system prompt and user prompt both went to the judge.
    assert len(chat.calls) == 1
    sys_msg, _ = chat.calls[0]
    assert sys_msg[0]["role"] == "system"
    assert "planning" in sys_msg[0]["content"]


def test_judge_run_handles_garbage_response() -> None:
    chat = ScriptedChat("not json at all, just prose")
    s = _state(_tc("read_file"), final="x")
    r = judge_run(state=s, chat=chat, user_prompt="x")
    # Default-low: every axis is 1.
    assert all(v == 1 for v in r.scores().values())
    assert "could not parse" in r.evidence()["planning"]


def test_judge_run_handles_backend_exception() -> None:
    def boom(messages, tools):
        raise RuntimeError("network down")

    s = _state(_tc("read_file"), final="x")
    r = judge_run(state=s, chat=boom, user_prompt="x")
    assert r.error is not None
    assert "network down" in r.error
    assert all(v == 1 for v in r.scores().values())


def test_judge_run_includes_audit_json_in_user_prompt() -> None:
    chat = ScriptedChat('{"scores": {"planning": 3, "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3}}')
    s = _state(_tc("read_file", {"path": "x.py"}), final="done")
    judge_run(state=s, chat=chat, user_prompt="read x.py")
    user_msg = chat.calls[0][0][1]
    assert "tool_calls" in user_msg["content"]
    assert "x.py" in user_msg["content"]


# --- Median / report helpers -----------------------------------------------


def test_judge_report_median_score_odd_count() -> None:
    r = JudgeReport(
        parsed={
            "scores": {"planning": 1, "recovery": 3, "honesty": 5, "minimality": 4, "safety": 2},
            "evidence": {},
        }
    )
    assert r.median_score() == 3  # middle of [1,2,3,4,5]


def test_judge_report_median_score_even_count() -> None:
    r = JudgeReport(
        parsed={
            "scores": {"planning": 1, "recovery": 2, "honesty": 4, "minimality": 4, "safety": 4},
            "evidence": {},
        }
    )
    # median of [1,2,4,4,4] = 4
    assert r.median_score() == 4


def test_judge_panel_aggregates_median() -> None:
    def chat_factory(scores: dict[str, int]):
        def chat(messages, tools):
            return ChatResponse(
                content=json.dumps({"scores": scores, "evidence": {}}),
                tool_calls=[],
                raw={},
            )
        return chat

    s = _state(_tc("read_file"), final="x")
    panel = judge_panel(
        state=s,
        judges=[
            ("a", chat_factory({"planning": 1, "recovery": 1, "honesty": 1, "minimality": 1, "safety": 1})),
            ("b", chat_factory({"planning": 5, "recovery": 5, "honesty": 5, "minimality": 5, "safety": 5})),
            ("c", chat_factory({"planning": 3, "recovery": 3, "honesty": 3, "minimality": 3, "safety": 3})),
        ],
        user_prompt="x",
    )
    # Median of [1, 3, 5] = 3
    assert panel.median_scores == {
        "planning": 3,
        "recovery": 3,
        "honesty": 3,
        "minimality": 3,
        "safety": 3,
    }
    assert len(panel.reports) == 3


def test_judge_panel_empty() -> None:
    s = _state(_tc("read_file"), final="x")
    panel = judge_panel(state=s, judges=[], user_prompt="x")
    assert panel.median_scores == {}
    assert panel.reports == []


def test_judge_report_to_dict() -> None:
    r = JudgeReport(
        parsed={
            "scores": {"planning": 4, "recovery": 4, "honesty": 4, "minimality": 4, "safety": 4},
            "evidence": {},
        },
        latency_ms=123,
        model="judge-x",
    )
    d = r.to_dict()
    assert d["median_score"] == 4
    assert d["model"] == "judge-x"
    assert d["latency_ms"] == 123
