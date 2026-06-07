"""Configuration models for prompts, backends, and runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class Prompt(BaseModel):
    """A single test prompt."""

    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt id must not be empty")
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
        allowed = {"ollama", "openai", "anthropic", "claude_cli", "codex_cli", "command"}
        if v not in allowed:
            raise ValueError(f"backend type must be one of {sorted(allowed)}, got {v!r}")
        return v


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
