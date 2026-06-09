"""Types for the agent driver loop.

These are pure data classes — no I/O, no model calls. The driver in
`driver.py` produces a `RunState` as it goes; the result is what gets
persisted to the audit trail and graded.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    """One tool call made by the agent, with its result.

    `ok=False` is the *recorded* outcome — including tools that returned
    a structured error result. The driver never raises out of a tool
    call; the model always gets the result back.
    """

    step_index: int
    tool_name: str
    arguments: Mapping[str, Any]
    ok: bool
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ModelResponse:
    """What the chat backend returned for one step.

    Exactly one of `content` (text) or `tool_calls` (>=1) is populated
    in practice, but a model *can* return both. `final_answer` is the
    sentinel-mode termination signal.
    """

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_final_answer(self) -> bool:
        return self.final_answer is not None


@dataclass
class RunState:
    """End-state of one agentic run.

    `messages` is the full chat history (system + user + assistant +
    tool results). `tool_calls` is the audit trail. `final_answer` is
    the model's terminal answer if it emitted one. `completed_normally`
    is True iff the model emitted a <done/> sentinel within the step
    budget; False means the driver hit `max_steps` or an unrecoverable
    error.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_answer: str | None = None
    completed_normally: bool = False
    total_steps: int = 0
    error: str | None = None
