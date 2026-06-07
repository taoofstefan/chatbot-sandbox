"""Generic subprocess backend: runs any command with the prompt on stdin."""

from __future__ import annotations

import shutil
import subprocess

from .base import Backend, BackendError, RunResult


class CommandBackend(Backend):
    """Runs an arbitrary CLI command. The prompt is passed via stdin.

    config.command must be a list, e.g. ["my-cli", "--quiet", "--format", "text"].
    config.model is recorded as the visible model name.
    """

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
