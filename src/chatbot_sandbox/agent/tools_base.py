"""Base class and registry for agent tools.

A tool is a small unit of side-effecting capability that the model can
invoke during an agentic run. The driver loop calls `tool.execute(args,
sandbox)` and writes the returned `ToolResult` into the audit trail.

The registry is the *allowlist* of tool names a case can use. The driver
refuses to call a tool that isn't in the registry.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .sandbox import Sandbox, SandboxError


class ToolError(RuntimeError):
    """Raised by a tool when its arguments are invalid or execution fails.

    The driver catches this and feeds a structured error back to the model.
    Tools should raise ToolError for *expected* failure modes (bad path,
    command not found, etc.) and let unexpected exceptions propagate so
    the driver can record them as bugs in the tool itself.
    """


@dataclass
class ToolResult:
    """Outcome of one tool call.

    `ok` is the single most important field: graders walk the audit
    trail and look at it. `output` is a JSON-serializable dict; it gets
    embedded in the model's context for the next step, so size matters
    (callers can truncate large outputs before returning).
    """

    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Tool:
    """A registered tool: name, schema, and execute().

    The `name` is the string the model (or sentinel parser) uses to call
    the tool. The `schema` is a JSON Schema describing `args`; it's
    embedded in the system prompt so the model knows what shape to send.
    `description` is a one-line explanation shown in the system prompt.
    """

    name: str
    description: str
    schema: Mapping[str, Any]
    execute: ToolExecutor


class ToolExecutor(ABC):
    """Pluggable execution strategy for a tool.

    Subclass and implement `__call__(args, sandbox) -> ToolResult`. Tools
    are stateless beyond their `__init__`; the driver constructs them
    once per registry and reuses the instance across steps.
    """

    @abstractmethod
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        ...


class ToolRegistry:
    """Allowlist of tools available to a given agentic run.

    Build one per case via `ToolRegistry.default()` (the standard 9 tools
    from the design doc) or `ToolRegistry.from_names(names, registry)`
    (a subset). The driver looks up a tool by name and refuses if the
    name isn't in the registry.
    """

    def __init__(self, tools: Mapping[str, Tool]) -> None:
        self._tools: dict[str, Tool] = dict(tools)

    @classmethod
    def default(cls) -> ToolRegistry:
        """Build a registry with all 9 standard tools wired up.

        Each call returns a fresh registry with its own
        `CommunicationStore`, so per-run state (drafts, approvals, sent
        messages) does not leak across runs.
        """
        from .communication_tools import (
            ApproveMessageTool,
            CommunicationStore,
            DraftMessageTool,
            SendMessageTool,
        )
        from .filesystem_tools import (
            EditFileTool,
            ListDirTool,
            ReadFileTool,
            SearchFilesTool,
            WriteFileTool,
        )
        from .shell_tool import RunShellTool

        store = CommunicationStore()
        executors: dict[str, ToolExecutor] = {
            "list_dir": ListDirTool(),
            "read_file": ReadFileTool(),
            "edit_file": EditFileTool(),
            "write_file": WriteFileTool(),
            "search_files": SearchFilesTool(),
            "run_shell": RunShellTool(),
            "draft_message": DraftMessageTool(store),
            "approve_message": ApproveMessageTool(store),
            "send_message": SendMessageTool(store),
        }
        tools = {name: _make_tool(name, exec_) for name, exec_ in executors.items()}
        return cls(tools)

    @classmethod
    def from_names(cls, names: list[str], base: ToolRegistry | None = None) -> ToolRegistry:
        """Restrict a registry to a subset of tool names.

        Useful for cases that only allow, e.g., [read_file, edit_file,
        run_shell]. Unknown names raise immediately so a typo in the
        prompts.yaml surfaces as a clear error at validation time.
        """
        base = base or cls.default()
        unknown = [n for n in names if n not in base._tools]
        if unknown:
            raise ValueError(
                f"unknown tool(s) {unknown}; "
                f"available: {sorted(base._tools)}"
            )
        return cls({n: base._tools[n] for n in names})

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(f"tool not in registry: {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def system_prompt_block(self) -> str:
        """Render the tool catalog for the system prompt (sentinel mode).

        In native function-calling mode, the backend builds this from the
        schema itself. The sentinel mode uses this rendered form.
        """
        lines = ["You have access to the following tools:"]
        for name in self.names():
            t = self._tools[name]
            lines.append("")
            lines.append(f"## {name}")
            lines.append(t.description)
            lines.append("Args (JSON Schema):")
            lines.append(json.dumps(t.schema, indent=2))
        lines.append("")
        lines.append(
            "To call a tool, emit exactly:\n"
            "<tool_call>\n"
            '{"name": "<tool_name>", "arguments": {...}}\n'
            "</tool_call>\n"
            "\n"
            "When you are done, emit exactly:\n"
            "<done/>\n"
            "<final_answer>\n"
            "...\n"
            "</final_answer>"
        )
        return "\n".join(lines)


def _make_tool(name: str, executor: ToolExecutor) -> Tool:
    """Look up the canned schema/description for a known tool name.

    Centralizing this keeps the executor classes free of metadata and
    makes it obvious what the model sees in its system prompt.
    """
    catalog = _TOOL_CATALOG.get(name)
    if catalog is None:
        raise ValueError(f"no catalog entry for tool {name!r}")
    return Tool(
        name=name,
        description=catalog["description"],
        schema=catalog["schema"],
        execute=executor,
    )


_TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "list_dir": {
        "description": "List entries in a directory relative to the working directory.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path. Use '.' for the repo root.",
                }
            },
            "required": ["path"],
        },
    },
    "read_file": {
        "description": "Read the contents of a file relative to the working directory.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_lines": {"type": "integer", "default": 500},
            },
            "required": ["path"],
        },
    },
    "edit_file": {
        "description": (
                "Replace an exact text snippet in a file. The old_text must "
                "appear exactly once in the file or the call fails."
            ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    "write_file": {
        "description": "Create a new file (refuses if the file already exists).",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    "search_files": {
        "description": "Search for a regex pattern across files (ripgrep).",
        "schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
        },
    },
    "run_shell": {
        "description": (
                "Run a shell command in the working directory. The command "
                "is checked against a safety blocklist before execution."
            ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_s": {"type": "integer", "default": 30},
            },
            "required": ["command"],
        },
    },
    "draft_message": {
        "description": "Draft an outbound message. Returns a draft_id.",
        "schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "approve_message": {
        "description": "Mark a draft as approved for sending.",
        "schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"],
        },
    },
    "send_message": {
        "description": (
                "Send a previously-drafted and approved message. Will be "
                "rejected if approve_message was not called for the same draft_id."
            ),
        "schema": {
            "type": "object",
            "properties": {"draft_id": {"type": "string"}},
            "required": ["draft_id"],
        },
    },
}


__all__ = [
    "SandboxError",
    "Tool",
    "ToolError",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
]
