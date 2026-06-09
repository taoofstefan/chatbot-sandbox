"""Filesystem tools: list_dir, read_file, edit_file, write_file, search_files.

All five resolve paths through the sandbox and reject anything outside
the workdir. They share a small `_read_text_file` helper and return
JSON-serializable dicts.

Every tool catches the same trio of expected errors and turns them into
a `ToolResult(ok=False, ...)`. Anything else propagates so a real bug
is loud, not silent.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from .sandbox import Sandbox, SandboxError
from .tools_base import ToolError, ToolExecutor, ToolResult

# Catches the union of "expected" failures: domain errors from this
# module (ToolError), sandbox rejections (SandboxError), and OS-level
# errors (OSError). Anything else propagates as a real bug.
_CAUGHT: tuple[type[BaseException], ...] = (ToolError, SandboxError, OSError)


def _ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _read_text_file(path: Path, max_lines: int) -> tuple[str, bool]:
    """Read a text file. Returns (content, truncated).

    Tries UTF-8, falls back to UTF-8 with replacement, never raises on
    encoding — the model should see the bytes, not a crash.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    if len(lines) > max_lines:
        return "".join(lines[:max_lines]), True
    return text, False


class ListDirTool(ToolExecutor):
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            path = sandbox.resolve(args.get("path", "."))
            if not path.exists():
                raise ToolError(f"path does not exist: {args.get('path')!r}")
            if not path.is_dir():
                raise ToolError(f"not a directory: {args.get('path')!r}")
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                entries.append(
                    {
                        "name": child.name,
                        "kind": "dir" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                )
            return ToolResult(
                ok=True,
                output={"entries": entries},
                duration_ms=_ms_since(t0),
            )
        except _CAUGHT as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class ReadFileTool(ToolExecutor):
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            path_arg = args.get("path")
            if not isinstance(path_arg, str):
                raise ToolError("read_file: 'path' is required")
            max_lines = int(args.get("max_lines", 500))
            path = sandbox.resolve(path_arg)
            if not path.exists():
                raise ToolError(f"file does not exist: {path_arg!r}")
            if path.is_dir():
                raise ToolError(f"is a directory, not a file: {path_arg!r}")
            content, truncated = _read_text_file(path, max_lines)
            return ToolResult(
                ok=True,
                output={"content": content, "truncated": truncated, "lines": content.count("\n") + 1},
                duration_ms=_ms_since(t0),
            )
        except _CAUGHT as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class EditFileTool(ToolExecutor):
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            for key in ("path", "old_text", "new_text"):
                if not isinstance(args.get(key), str):
                    raise ToolError(f"edit_file: '{key}' is required and must be a string")
            path = sandbox.resolve(args["path"])
            if not path.exists():
                raise ToolError(f"file does not exist: {args['path']!r}")
            text = path.read_text(encoding="utf-8", errors="replace")
            occurrences = text.count(args["old_text"])
            if occurrences == 0:
                raise ToolError("old_text not found in file")
            if occurrences > 1:
                raise ToolError(
                    f"old_text matches {occurrences} locations; must match exactly one. "
                    "Provide more surrounding context."
                )
            new_text = text.replace(args["old_text"], args["new_text"], 1)
            path.write_text(new_text, encoding="utf-8")
            return ToolResult(
                ok=True,
                output={"path": args["path"], "bytes_written": len(new_text) - len(text)},
                duration_ms=_ms_since(t0),
            )
        except _CAUGHT as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class WriteFileTool(ToolExecutor):
    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            for key in ("path", "content"):
                if not isinstance(args.get(key), str):
                    raise ToolError(f"write_file: '{key}' is required and must be a string")
            path = sandbox.resolve(args["path"])
            if path.exists():
                raise ToolError(
                    f"file already exists: {args['path']!r}. "
                    "Use edit_file to modify, or delete first."
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return ToolResult(
                ok=True,
                output={"path": args["path"], "bytes_written": len(args["content"])},
                duration_ms=_ms_since(t0),
            )
        except _CAUGHT as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))


class SearchFilesTool(ToolExecutor):
    """ripgrep-backed regex search.

    Falls back to a pure-Python walker if rg is missing on the system.
    Output is capped at 200 matches to keep the model's context small.
    """

    MAX_MATCHES = 200

    def __call__(self, args: dict[str, Any], sandbox: Sandbox) -> ToolResult:
        t0 = time.perf_counter()
        try:
            pattern = args.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise ToolError("search_files: 'pattern' is required")
            try:
                re.compile(pattern)
            except re.error as e:
                raise ToolError(f"invalid regex: {e}") from e
            search_path = sandbox.resolve(args.get("path", "."))
            if not search_path.exists():
                raise ToolError(f"path does not exist: {args.get('path')!r}")

            matches = self._ripgrep(pattern, str(search_path))
            if matches is None:
                matches = self._python_walk(pattern, search_path)
            truncated = len(matches) > self.MAX_MATCHES
            matches = matches[: self.MAX_MATCHES]
            return ToolResult(
                ok=True,
                output={
                    "matches": matches,
                    "truncated": truncated,
                    "total_considered": len(matches),
                },
                duration_ms=_ms_since(t0),
            )
        except _CAUGHT as e:
            return ToolResult(ok=False, error=str(e), duration_ms=_ms_since(t0))

    @staticmethod
    def _ripgrep(pattern: str, path: str) -> list[dict[str, Any]] | None:
        """Try ripgrep; return None if rg is missing or fails."""
        import shutil
        import subprocess

        if shutil.which("rg") is None:
            return None
        try:
            proc = subprocess.run(
                ["rg", "--no-heading", "--line-number", "--no-messages", pattern, path],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if proc.returncode not in (0, 1):  # 0=matches, 1=no matches
            return None
        out: list[dict[str, Any]] = []
        rg_line_re = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<text>.*)$")
        for line in proc.stdout.splitlines():
            # rg --no-heading --line-number output: "<path>:<lineno>:<text>".
            # Use a regex so Windows drive-letter paths (C:\...) and any
            # colons in the matched text (e.g. function arg lists) survive.
            m = rg_line_re.match(line)
            if not m:
                continue
            out.append(
                {
                    "path": m.group("path"),
                    "line": int(m.group("line")),
                    "text": m.group("text"),
                }
            )
        return out

    @staticmethod
    def _python_walk(pattern: str, path: Path) -> list[dict[str, Any]]:
        rx = re.compile(pattern)
        out: list[dict[str, Any]] = []
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            try:
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if rx.search(line):
                            out.append({"path": str(p), "line": i, "text": line.rstrip("\n")})
            except OSError:
                continue
        return out
