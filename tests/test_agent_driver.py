"""Tests for the agent driver loop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chatbot_sandbox.agent import (
    Sandbox,
    ToolRegistry,
    parse_assistant_message,
    run_agent,
)
from chatbot_sandbox.backends.base import ChatResponse

# --- Test helpers ----------------------------------------------------------


class MockChat:
    """A scripted chat backend for testing the driver loop.

    Pass a list of `assistant_message` strings (or full ChatResponse-like
    dicts). Each call to `chat()` returns the next item. The `tools`
    argument is recorded for inspection.
    """

    def __init__(self, responses: list[str | dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[dict[str, object]], list[dict[str, object]] | None]] = []
        self.tools_seen: list[Any] = []

    def __call__(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        self.calls.append((list(messages), tools))
        if not self._responses:
            # Default to a benign "I'm done" so the driver terminates.
            return ChatResponse(
                content="<done/>\n<final_answer>\nout of scripted responses\n</final_answer>",
                tool_calls=[],
                raw={},
            )
        item = self._responses.pop(0)
        if isinstance(item, str):
            return ChatResponse(content=item, tool_calls=[], raw={})
        return ChatResponse(
            content=item.get("content", ""),
            tool_calls=list(item.get("tool_calls") or []),
            raw=item.get("raw") or {},
        )


def _make_sandbox_with_files(tmp_path: Path) -> Sandbox:
    """Sandbox with a few small files for tool tests."""
    fixture = tmp_path / "fix"
    fixture.mkdir()
    (fixture / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (fixture / "sub").mkdir()
    (fixture / "sub" / "note.md").write_text("a note", encoding="utf-8")
    return Sandbox.from_fixture(fixture)


# --- Basic loop behavior ---------------------------------------------------


def test_driver_runs_one_tool_call_then_done(tmp_path: Path) -> None:
    """Model reads a file then emits a final answer."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])
    chat = MockChat([
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "hello.txt"}}\n</tool_call>',
        "<done/>\n<final_answer>done reading</final_answer>",
    ])
    state = run_agent(
        user_prompt="read hello.txt and tell me what's in it",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=5,
    )
    assert state.completed_normally
    assert state.final_answer == "done reading"
    assert state.total_steps == 2
    assert len(state.tool_calls) == 1
    assert state.tool_calls[0].tool_name == "read_file"
    assert state.tool_calls[0].ok is True
    assert "hello world" in state.tool_calls[0].output["content"]


def test_driver_runs_multiple_tool_calls_in_one_step(tmp_path: Path) -> None:
    """A model can emit multiple <tool_call> blocks in one assistant message."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["list_dir", "read_file"])
    chat = MockChat([
        '<tool_call>\n{"name": "list_dir", "arguments": {"path": "."}}\n</tool_call>\n'
        '<tool_call>\n{"name": "read_file", "arguments": {"path": "hello.txt"}}\n</tool_call>',
        "<done/>\n<final_answer>ok</final_answer>",
    ])
    state = run_agent(
        user_prompt="list and read",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=5,
    )
    assert state.completed_normally
    assert len(state.tool_calls) == 2
    assert [tc.tool_name for tc in state.tool_calls] == ["list_dir", "read_file"]


def test_driver_stops_at_max_steps(tmp_path: Path) -> None:
    """If the model never emits a final answer, the driver hits max_steps."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["list_dir"])
    # Each turn emits a tool call (never done).
    chat = MockChat([
        '<tool_call>\n{"name": "list_dir", "arguments": {"path": "."}}\n</tool_call>',
        '<tool_call>\n{"name": "list_dir", "arguments": {"path": "sub"}}\n</tool_call>',
    ])
    state = run_agent(
        user_prompt="loop forever",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=2,
    )
    assert not state.completed_normally
    assert state.final_answer is None
    assert state.total_steps == 2
    assert "max_steps" in (state.error or "")


# --- Error handling --------------------------------------------------------


def test_driver_records_unknown_tool_as_failure(tmp_path: Path) -> None:
    """If the model calls a tool not in the registry, audit it, don't crash."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])
    chat = MockChat([
        '<tool_call>\n{"name": "run_shell", "arguments": {"command": "ls"}}\n</tool_call>',
        "<done/>\n<final_answer>never mind</final_answer>",
    ])
    state = run_agent(
        user_prompt="shell pls",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=5,
    )
    assert state.completed_normally
    assert state.tool_calls[0].ok is False
    assert "not in the allowlist" in (state.tool_calls[0].error or "")


def test_driver_records_malformed_tool_call(tmp_path: Path) -> None:
    """A <tool_call> with bad JSON is recorded as unparsed and shown to the model."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])
    chat = MockChat([
        "<tool_call>\n{not json}\n</tool_call>",
        "<done/>\n<final_answer>I give up</final_answer>",
    ])
    state = run_agent(
        user_prompt="read x",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=5,
    )
    assert state.completed_normally
    # The bad JSON produces no tool calls; the second turn emits done.
    assert state.tool_calls == []


def test_driver_handles_chat_exception(tmp_path: Path) -> None:
    """Backend exceptions are caught and surfaced in state.error."""

    def boom(_messages, _tools):
        raise RuntimeError("simulated backend failure")

    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])
    state = run_agent(
        user_prompt="x",
        sandbox=sb,
        registry=reg,
        chat=boom,
        max_steps=3,
    )
    assert not state.completed_normally
    assert "simulated backend failure" in (state.error or "")


# --- Native function-calling mode ------------------------------------------


def test_driver_native_mode_dispatches_structured_tool_calls(tmp_path: Path) -> None:
    """In native mode the backend returns structured tool_calls; driver just runs them."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])

    counter = {"n": 0}

    def native_chat(messages, tools):
        counter["n"] += 1
        if counter["n"] == 1:
            return ChatResponse(
                content="",
                tool_calls=[{"name": "read_file", "arguments": {"path": "hello.txt"}}],
                raw={},
            )
        return ChatResponse(
            content="I read it. The file says hello world.",
            tool_calls=[],
            raw={},
        )

    state = run_agent(
        user_prompt="read hello.txt",
        sandbox=sb,
        registry=reg,
        chat=native_chat,
        max_steps=5,
        use_native_tool_calling=True,
    )
    assert state.completed_normally
    assert state.final_answer == "I read it. The file says hello world."
    assert len(state.tool_calls) == 1
    assert state.tool_calls[0].ok is True
    assert "hello world" in state.tool_calls[0].output["content"]


def test_driver_native_mode_does_not_parse_sentinels(tmp_path: Path) -> None:
    """In native mode, <done/> in content is irrelevant — empty tool_calls == done."""
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file"])

    def native_chat(messages, tools):
        return ChatResponse(
            content="no <done/> sentinel here, just text",
            tool_calls=[],
            raw={},
        )

    state = run_agent(
        user_prompt="x",
        sandbox=sb,
        registry=reg,
        chat=native_chat,
        max_steps=5,
        use_native_tool_calling=True,
    )
    assert state.completed_normally
    assert state.final_answer == "no <done/> sentinel here, just text"


# --- System prompt ---------------------------------------------------------


def test_driver_includes_tool_catalog_in_system_prompt(tmp_path: Path) -> None:
    sb = _make_sandbox_with_files(tmp_path)
    reg = ToolRegistry.from_names(["read_file", "edit_file"])
    chat = MockChat(["<done/>\n<final_answer>x</final_answer>"])
    run_agent(
        user_prompt="x",
        sandbox=sb,
        registry=reg,
        chat=chat,
        max_steps=2,
    )
    sys_msg = chat.calls[0][0][0]
    assert sys_msg["role"] == "system"
    assert "## read_file" in sys_msg["content"]
    assert "## edit_file" in sys_msg["content"]
    assert "<tool_call>" in sys_msg["content"]


# --- Native tool schema rendering ------------------------------------------


def test_native_tool_schema_renders() -> None:
    from chatbot_sandbox.agent import render_tool_for_native

    reg = ToolRegistry.from_names(["read_file"])
    schema = render_tool_for_native("read_file", reg)
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "read_file"
    assert "properties" in schema["function"]["parameters"]
    assert "path" in schema["function"]["parameters"]["properties"]


# --- Sentinel parser re-export smoke ---------------------------------------


def test_sentinel_parser_is_exposed_via_package() -> None:
    """The package's re-export of `parse_assistant_message` works."""
    r = parse_assistant_message(
        '<tool_call>\n{"name": "x", "arguments": {}}\n</tool_call>'
    )
    assert len(r.tool_calls) == 1
