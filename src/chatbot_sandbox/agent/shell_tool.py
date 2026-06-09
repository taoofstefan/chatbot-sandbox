"""run_shell tool: subprocess execution with a safety blocklist.

The blocklist is best-effort defense, not a security boundary. The v1
isolation story is temp-dir + blocklist (see design doc §3.2). A
determined model can still do damage if it finds a way around the
blocklist; v2 would containerize.

Blocklist rules (in order):
  1. Mass-delete: rm -rf /, rm -rf ~, rm -rf .
  2. Fork bomb: :(){:|:&};:
  3. Disk ops: mkfs, dd if=
  4. Network + exec: curl ... | sh, wget ... | sh
  5. System control: shutdown, reboot, halt, poweroff
  6. Disk overwrite: > /dev/sd*, > /dev/nvme*
  7. Shell-injection patterns: \beval\b, \bsource\b

Network egress is not explicitly blocked because the sandbox has no
route to the internet; a `curl` call will simply time out or get
"network unreachable". We still block the obvious network+exec combos
because the agent could find a way.
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from .sandbox import Sandbox, SandboxError
from .tools_base import ToolError, ToolExecutor, ToolResult

BLOCKED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+-rf\s+(/|~|\.)(?:\s|$)"),
    re.compile(r":\(\)\s*\{"),
    re.compile(r"\bmkfs(\.|\s)"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sh|bash)\b"),
    re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"),
    re.compile(r">\s*/dev/(sd|nvme|hd)"),
    re.compile(r"\beval\b"),
    re.compile(r"\bsource\b"),
)

MAX_OUTPUT_BYTES = 50_000
DEFAULT_TIMEOUT_S = 30
MAX_TIMEOUT_S = 300


def _is_blocked(command: str) -> str | None:
    """Return the offending pattern's description if the command is blocked, else None."""
    for rx in BLOCKED_PATTERNS:
        if rx.search(command):
            return rx.pattern
    return None


def _truncate(s: str, limit: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    """Cap string output to limit bytes. Returns (text, truncated)."""
    if len(s.encode("utf-8")) <= limit:
        return s, False
    # Truncate by characters, not bytes, to avoid splitting a multi-byte char.
    out = s[:limit]
    return out, True


class RunShellTool(ToolExecutor):
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            command = args.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ToolError("run_shell: 'command' is required")
            timeout = int(args.get("timeout_s", DEFAULT_TIMEOUT_S))
            if timeout < 1 or timeout > MAX_TIMEOUT_S:
                raise ToolError(
                    f"run_shell: timeout_s must be in [1, {MAX_TIMEOUT_S}], got {timeout}"
                )

            blocked = _is_blocked(command)
            if blocked is not None:
                return ToolResult(
                    ok=False,
                    error=f"command blocked by safety policy (matched: {blocked})",
                    duration_ms=_ms_since(t0),
                )

            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(sandbox.workdir),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            stdout, stdout_trunc = _truncate(proc.stdout or "")
            stderr, stderr_trunc = _truncate(proc.stderr or "")
            return ToolResult(
                ok=proc.returncode == 0,
                output={
                    "exit_code": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_trunc,
                    "stderr_truncated": stderr_trunc,
                },
                error=None if proc.returncode == 0 else f"exit {proc.returncode}",
                duration_ms=_ms_since(t0),
            )
        except subprocess.TimeoutExpired as e:
            # `e.stdout` / `e.stderr` are typed `bytes | str` at the type
            # level, but in practice they're str because we ran with text=True.
            # Coerce defensively rather than letting the mypy union confuse us.
            stdout = e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            return ToolResult(
                ok=False,
                error=f"command timed out after {timeout}s",
                output={
                    "stdout": _truncate(stdout)[0],
                    "stderr": _truncate(stderr)[0],
                },
                duration_ms=_ms_since(t0),
            )
        except (ToolError, SandboxError) as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
