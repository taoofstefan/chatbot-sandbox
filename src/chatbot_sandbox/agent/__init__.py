"""Agentic benchmark subsystem.

Public surface for steps 2-3 (tools, sandbox, driver). Judges, the
`cbs run-agent` CLI, and the rubric templates arrive in later steps.
"""

from __future__ import annotations

from ..backends.base import ChatResponse
from .communication_tools import CommunicationStore
from .driver import (
    ChatFn,
    agent_run_to_state,
    build_system_prompt,
    grade_run,
    render_tool_for_native,
    run_agent,
    run_state_to_dict,
    to_model_response,
)
from .graders import KNOWN_AGENT_CHECKS, grade_agent
from .judges import (
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_TEMPLATE,
    JudgeReport,
    PanelResult,
    judge_panel,
    judge_run,
    parse_judge_response,
    render_audit_for_judge,
)
from .judges import (
    ChatFn as JudgeChatFn,
)
from .sandbox import Sandbox, SandboxError
from .sentinel import ParsedToolCall, ParseResult, parse_assistant_message
from .state import ModelResponse, RunState, ToolCallRecord
from .tools_base import Tool, ToolError, ToolExecutor, ToolRegistry, ToolResult

__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "JUDGE_USER_TEMPLATE",
    "KNOWN_AGENT_CHECKS",
    "ChatFn",
    "ChatResponse",
    "CommunicationStore",
    "JudgeChatFn",
    "JudgeReport",
    "ModelResponse",
    "PanelResult",
    "ParseResult",
    "ParsedToolCall",
    "RunState",
    "Sandbox",
    "SandboxError",
    "Tool",
    "ToolCallRecord",
    "ToolError",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "agent_run_to_state",
    "build_system_prompt",
    "grade_agent",
    "grade_run",
    "judge_panel",
    "judge_run",
    "parse_assistant_message",
    "parse_judge_response",
    "render_audit_for_judge",
    "render_tool_for_native",
    "run_agent",
    "run_state_to_dict",
    "to_model_response",
]
