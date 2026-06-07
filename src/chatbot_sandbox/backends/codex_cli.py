"""Codex CLI backend - thin wrapper over CommandBackend."""

from __future__ import annotations

from .base import RunResult
from .command import CommandBackend


class CodexCliBackend(CommandBackend):
    """Runs `codex exec` non-interactively."""

    def run(self, prompt: str) -> RunResult:
        if not self.config.command:
            object.__setattr__(
                self.config, "command", ["codex", "exec", "-"]
            )
        return super().run(prompt)
