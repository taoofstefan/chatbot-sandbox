"""Generic subprocess backend: runs any command with the prompt on stdin."""

from __future__ import annotations

import shutil
import subprocess

from .base import Backend, BackendError, ChatResponse, RunResult


class CommandBackend(Backend):
    """Runs an arbitrary CLI command. The prompt is passed via stdin.

    config.command must be a list, e.g. ["my-cli", "--quiet", "--format", "text"].
    config.model is recorded as the visible model name.
    """

    supports_chat = True

    def run(self, prompt: str) -> RunResult:
        cmd = self.config.command
        if not cmd:
            raise BackendError("command backend requires 'command' (list)")
        if not shutil.which(cmd[0]):
            return RunResult(
                error=f"command not found on PATH: {cmd[0]}",
                model=self.config.model,
            )
        with self._time() as t:
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt.encode("utf-8"),
                    capture_output=True,
                    timeout=self.config.timeout,
                )
            except subprocess.TimeoutExpired:
                return RunResult(
                    error=f"timeout after {self.config.timeout}s",
                    latency_ms=t.elapsed_ms,
                    model=self.config.model,
                )
            except Exception as e:
                return RunResult(
                    error=f"command: {e}",
                    latency_ms=t.elapsed_ms,
                    model=self.config.model,
                )

        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            return RunResult(
                error=f"exit {proc.returncode}: {err or 'no stderr'}",
                latency_ms=t.elapsed_ms,
                model=self.config.model,
            )
        return RunResult(
            output=proc.stdout.decode("utf-8", errors="replace"),
            latency_ms=t.elapsed_ms,
            model=self.config.model,
        )

    def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        """Multi-turn chat via the configured command.

        The command is run with the last user-message content on stdin, and
        its stdout becomes the assistant message content. `tools` is ignored
        — command backends can't do native function-calling, so callers drive
        them in sentinel mode (the model's text is parsed for tool blocks /
        ``<done/>`` by the driver). A run error is raised as `BackendError`,
        which the agent driver records into `RunState.error`.

        This makes the agent driver (and the LLM-judge panel) exercisable with
        deterministic scripted commands and no network, reusing the same
        ``type: command`` config the single-turn path already uses.
        """
        last_user = next(
            (
                m
                for m in reversed(messages)
                if isinstance(m, dict) and m.get("role") == "user"
            ),
            None,
        )
        prompt = str((last_user or {}).get("content", ""))
        result = self.run(prompt)
        if result.error:
            raise BackendError(result.error)
        return ChatResponse(content=result.output)
