"""Backend registry / factory."""

from __future__ import annotations

from ..config import BackendConfig
from .anthropic_backend import AnthropicBackend
from .base import Backend
from .claude_cli import ClaudeCliBackend
from .codex_cli import CodexCliBackend
from .command import CommandBackend
from .ollama import OllamaBackend
from .openai_backend import OpenAIBackend

_REGISTRY: dict[str, type[Backend]] = {
    "ollama": OllamaBackend,
    "openai": OpenAIBackend,
    "anthropic": AnthropicBackend,
    "claude_cli": ClaudeCliBackend,
    "codex_cli": CodexCliBackend,
    "command": CommandBackend,
}


def known_types() -> list[str]:
    return sorted(_REGISTRY)


def build_backend(config: BackendConfig) -> Backend:
    cls = _REGISTRY.get(config.type)
    if cls is None:
        raise ValueError(f"unknown backend type: {config.type}")
    return cls(config)
