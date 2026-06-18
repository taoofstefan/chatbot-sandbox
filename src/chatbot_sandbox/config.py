"""Configuration models for prompts, backends, and runs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

BACKEND_TYPES: frozenset[str] = frozenset(
    {"ollama", "openai", "anthropic", "claude_cli", "codex_cli", "command"}
)

KNOWN_AGENT_TOOLS: frozenset[str] = frozenset(
    {
        "list_dir",
        "read_file",
        "edit_file",
        "write_file",
        "search_files",
        "run_shell",
        "draft_message",
        "approve_message",
        "send_message",
    }
)


class AgentConfig(BaseModel):
    """Agentic-mode settings for a prompt.

    When `Prompt.agent` is set, the agent driver loop is used instead of
    a single chat call. A prompt without `agent:` falls back to the
    existing single-turn path; this is fully backwards-compatible.

    `fixture` is an optional path (relative to the working directory the
    CLI is run from) to a directory copied into a fresh per-run sandbox.
    When None the agent runs against an empty sandbox.
    """

    tools: list[str]
    max_steps: int = 15
    step_timeout_s: int = 30
    workdir: str | None = None
    fixture: str | None = None
    commit_required: bool = False
    use_native_tool_calling: bool | None = None

    @field_validator("tools")
    @classmethod
    def _tools_known(cls, v: list[str]) -> list[str]:
        unknown = [t for t in v if t not in KNOWN_AGENT_TOOLS]
        if unknown:
            raise ValueError(
                f"unknown agent tool(s) {unknown}; known: {sorted(KNOWN_AGENT_TOOLS)}"
            )
        if not v:
            raise ValueError("agent.tools must list at least one tool")
        return v

    @field_validator("max_steps")
    @classmethod
    def _max_steps_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_steps must be >= 1")
        return v


class Prompt(BaseModel):
    """A single test prompt."""

    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    validators: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional inline assertions evaluated against each model output. "
            "Keys are check names (see chatbot_sandbox.graders), values are "
            "the expected value or a list of arguments."
        ),
    )
    agent: AgentConfig | None = None

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt id must not be empty")
        return v

    @field_validator("validators")
    @classmethod
    def _validators_known(cls, v: dict[str, Any]) -> dict[str, Any]:
        # Imported lazily to keep config.py free of runtime dependencies.
        # Single-turn prompts use `graders.KNOWN_CHECKS`; agent prompts use
        # `agent.graders.KNOWN_AGENT_CHECKS`. Accept the union so a prompts
        # file may mix both kinds.
        from .agent.graders import KNOWN_AGENT_CHECKS
        from .graders import KNOWN_CHECKS

        known = KNOWN_CHECKS | KNOWN_AGENT_CHECKS
        unknown = [k for k in v if k not in known]
        if unknown:
            raise ValueError(
                f"unknown validator(s) {unknown}; known: {sorted(known)}"
            )
        return v


class PromptSet(BaseModel):
    """A named collection of prompts."""

    name: str
    description: str = ""
    prompts: list[Prompt]

    @classmethod
    def from_yaml(cls, path: Path) -> PromptSet:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected mapping at top level")
        return cls.model_validate(data)

    def to_yaml(self, path: Path) -> None:
        path.write_text(
            yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


class BackendConfig(BaseModel):
    """Configuration for a single backend instance."""

    name: str
    type: str  # ollama, openai, anthropic, claude_cli, codex_cli, command
    model: str | None = None
    command: list[str] | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 120.0
    cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in BACKEND_TYPES:
            raise ValueError(
                f"backend type must be one of {sorted(BACKEND_TYPES)}, got {v!r}"
            )
        return v

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: Mapping[str, Any], handler: Any
    ) -> dict[str, Any]:
        out: dict[str, Any] = dict(handler(schema))
        if "properties" in out and "type" in out["properties"]:
            out["properties"]["type"]["enum"] = sorted(BACKEND_TYPES)
            out["properties"]["type"]["description"] = (
                "Backend implementation: " + ", ".join(sorted(BACKEND_TYPES))
            )
        return out


class BackendSet(BaseModel):
    """A collection of backend configurations."""

    backends: list[BackendConfig]

    @classmethod
    def from_yaml(cls, path: Path) -> BackendSet:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "backends" in data:
            return cls.model_validate(data)
        if isinstance(data, list):
            return cls(backends=[BackendConfig.model_validate(b) for b in data])
        raise ValueError(f"{path}: expected list or {{backends: [...]}}")

    def find(self, names: list[str] | None = None) -> list[BackendConfig]:
        if not names:
            return list(self.backends)
        by_name = {b.name: b for b in self.backends}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(f"unknown backend(s): {missing}. Available: {list(by_name)}")
        return [by_name[n] for n in names]
