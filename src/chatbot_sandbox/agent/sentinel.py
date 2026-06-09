"""Sentinel parser for tool calls in free-form model output.

When a backend doesn't support native function calling, the driver
falls back to a sentinel format:

    <tool_call>
    {"name": "<tool_name>", "arguments": {...}}
    </tool_call>

    <done/>
    <final_answer>
    ...
    </final_answer>

This module parses that format. It is intentionally permissive: a
malformed `<tool_call>` block is reported back to the model as a tool
error (the same way a backend API error would be), not a crash.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(?P<body>.*?)\s*</tool_call>", re.DOTALL)
_FINAL_ANSWER_RE = re.compile(
    r"<done\s*/?>\s*<final_answer>\s*(?P<body>.*?)\s*</final_answer>",
    re.DOTALL | re.IGNORECASE,
)
_DONE_ONLY_RE = re.compile(r"<done\s*/?>", re.IGNORECASE)


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]
    """Raw text of the <tool_call> body, for error reporting."""
    raw: str


@dataclass
class ParseResult:
    """The outcome of parsing one assistant message.

    Fields are independent: a message may contain zero or more tool
    calls AND a final answer (the latter typically means "I am done").
    `unparsed_tool_calls` captures the *malformed* ones so the driver
    can feed them back as a structured error.
    """

    tool_calls: list[ParsedToolCall]
    final_answer: str | None
    unparsed_tool_calls: list[str]


def parse_assistant_message(content: str) -> ParseResult:
    """Extract tool calls and the final-answer sentinel from `content`."""
    tool_calls: list[ParsedToolCall] = []
    unparsed: list[str] = []

    for m in _TOOL_CALL_RE.finditer(content):
        body = m.group("body").strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            unparsed.append(f"invalid JSON in <tool_call>: {e.msg} at pos {e.pos}")
            continue
        if not isinstance(data, dict):
            unparsed.append(f"<tool_call> body must be a JSON object, got {type(data).__name__}")
            continue
        name = data.get("name")
        args = data.get("arguments", {})
        if not isinstance(name, str) or not name:
            unparsed.append("<tool_call> missing 'name' (must be a non-empty string)")
            continue
        if not isinstance(args, dict):
            unparsed.append(
                f"<tool_call> 'arguments' must be a JSON object, got {type(args).__name__}"
            )
            continue
        tool_calls.append(ParsedToolCall(name=name, arguments=args, raw=body))

    final_answer: str | None = None
    fa_match = _FINAL_ANSWER_RE.search(content)
    if fa_match:
        final_answer = fa_match.group("body").strip()
    elif _DONE_ONLY_RE.search(content) and not tool_calls:
        # <done/> without <final_answer> is allowed; treat as empty answer.
        final_answer = ""

    return ParseResult(
        tool_calls=tool_calls,
        final_answer=final_answer,
        unparsed_tool_calls=unparsed,
    )


def iter_tool_blocks(content: str) -> Iterator[tuple[int, int]]:
    """Yield (start, end) char offsets of every <tool_call> block in `content`.

    Useful for stripping the blocks from the content before sending it
    back to the model as the assistant turn, so the model doesn't
    re-parse its own output.
    """
    for m in _TOOL_CALL_RE.finditer(content):
        yield m.start(), m.end()


def strip_tool_blocks(content: str) -> str:
    """Return `content` with all <tool_call>...</tool_call> blocks removed."""
    out: list[str] = []
    cursor = 0
    for start, end in iter_tool_blocks(content):
        out.append(content[cursor:start])
        cursor = end
    out.append(content[cursor:])
    return "".join(out)
