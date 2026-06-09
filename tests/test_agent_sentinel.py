"""Tests for the sentinel parser."""

from __future__ import annotations

from chatbot_sandbox.agent.sentinel import (
    iter_tool_blocks,
    parse_assistant_message,
    strip_tool_blocks,
)


def test_parse_single_tool_call() -> None:
    msg = (
        "Let me read the file first.\n"
        "<tool_call>\n"
        '{"name": "read_file", "arguments": {"path": "src/foo.py"}}\n'
        "</tool_call>"
    )
    r = parse_assistant_message(msg)
    assert len(r.tool_calls) == 1
    tc = r.tool_calls[0]
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "src/foo.py"}
    assert r.final_answer is None
    assert r.unparsed_tool_calls == []


def test_parse_multiple_tool_calls() -> None:
    msg = (
        "<tool_call>\n"
        '{"name": "list_dir", "arguments": {"path": "."}}\n'
        "</tool_call>\n"
        "<tool_call>\n"
        '{"name": "read_file", "arguments": {"path": "x.py"}}\n'
        "</tool_call>"
    )
    r = parse_assistant_message(msg)
    assert [tc.name for tc in r.tool_calls] == ["list_dir", "read_file"]


def test_parse_final_answer_with_done() -> None:
    msg = (
        "All done.\n"
        "<done/>\n"
        "<final_answer>\n"
        "Fixed the off-by-one in src/foo.py:5.\n"
        "Verified by running pytest -q.\n"
        "</final_answer>"
    )
    r = parse_assistant_message(msg)
    assert r.tool_calls == []
    assert r.final_answer is not None
    assert "Fixed the off-by-one" in r.final_answer
    assert "pytest -q" in r.final_answer


def test_parse_done_without_final_answer() -> None:
    msg = "I give up. <done/>"
    r = parse_assistant_message(msg)
    assert r.tool_calls == []
    assert r.final_answer == ""


def test_parse_malformed_json_recorded_as_unparsed() -> None:
    msg = "<tool_call>\n{this is not json}\n</tool_call>"
    r = parse_assistant_message(msg)
    assert r.tool_calls == []
    assert len(r.unparsed_tool_calls) == 1
    assert "invalid JSON" in r.unparsed_tool_calls[0]


def test_parse_missing_name_recorded_as_unparsed() -> None:
    msg = "<tool_call>\n{\"arguments\": {\"path\": \"x\"}}\n</tool_call>"
    r = parse_assistant_message(msg)
    assert r.tool_calls == []
    assert "missing 'name'" in r.unparsed_tool_calls[0]


def test_parse_arguments_must_be_object() -> None:
    msg = '<tool_call>\n{"name": "x", "arguments": "not a dict"}\n</tool_call>'
    r = parse_assistant_message(msg)
    assert r.tool_calls == []
    assert "JSON object" in r.unparsed_tool_calls[0]


def test_parse_handles_tool_call_with_done_in_same_message() -> None:
    """A model can do one last tool call AND announce completion in the same turn."""
    msg = (
        "<tool_call>\n"
        '{"name": "run_shell", "arguments": {"command": "pytest -q"}}\n'
        "</tool_call>\n"
        "<done/>\n"
        "<final_answer>All tests pass.</final_answer>"
    )
    r = parse_assistant_message(msg)
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "run_shell"
    assert r.final_answer == "All tests pass."


def test_parse_no_tool_calls_no_done() -> None:
    r = parse_assistant_message("Just thinking out loud here.")
    assert r.tool_calls == []
    assert r.final_answer is None
    assert r.unparsed_tool_calls == []


def test_iter_tool_blocks_returns_offsets() -> None:
    msg = "pre <tool_call>X</tool_call> post"
    offsets = list(iter_tool_blocks(msg))
    assert len(offsets) == 1
    s, e = offsets[0]
    assert msg[s:e] == "<tool_call>X</tool_call>"


def test_strip_tool_blocks_removes_blocks() -> None:
    msg = (
        "before "
        "<tool_call>\n"
        '{"name": "x", "arguments": {}}\n'
        "</tool_call>"
        " after"
    )
    assert strip_tool_blocks(msg) == "before  after"
