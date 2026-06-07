"""Claude CLI backend - thin wrapper over CommandBackend."""

from __future__ import annotations

from .base import RunResult
from .command import CommandBackend


class ClaudeCliBackend(CommandBackend):
    """Runs `claude -p` (print mode) non-interactively."""

    def run(self, prompt: str) -> RunResult:
        if not self.config.command:
            # sensible default
            object.__setattr__(
                self.config, "command", ["claude", "-p", "--output-format", "text"]
            )
        return super().run(prompt)
