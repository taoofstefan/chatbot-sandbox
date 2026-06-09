"""Per-run sandbox for agentic tool execution.

A Sandbox is a fresh copy of a fixture repo rooted at a known absolute
directory. Every tool that touches the filesystem resolves paths against
the sandbox root and rejects any path that escapes it (path-traversal
defense). Symlinks are not followed, both for security and because
fixtures shouldn't depend on them.

The sandbox is intentionally simple: it's a `tempfile.TemporaryDirectory`
plus a copied fixture tree. It is NOT a container; the run_shell tool's
blocklist is the primary safety net. See the design doc for the v1
isolation story.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class SandboxError(RuntimeError):
    """Raised when a path is outside the sandbox, the fixture is missing, etc."""


@dataclass
class Sandbox:
    """An isolated working directory for one (case, model) run.

    `workdir` is the root the agent sees. All tool paths are resolved
    relative to it. The sandbox owns its underlying temp dir; call
    `cleanup()` to release it (also called automatically on garbage
    collection via `__exit__` support).
    """

    workdir: Path
    _owns_tempdir: Path | None = None

    @classmethod
    def from_fixture(cls, fixture_path: Path, *, copy: bool = True) -> Sandbox:
        """Create a sandbox by copying a fixture directory to a temp dir.

        Args:
            fixture_path: Absolute or relative path to the fixture repo.
            copy: If True (default), the fixture is COPIED so the agent's
                  edits don't affect the checked-in source. If False, a
                  read-only view is used (for graders that want to inspect
                  the original).

        Raises:
            SandboxError: If the fixture doesn't exist or isn't a directory.
        """
        fixture_path = fixture_path.resolve()
        if not fixture_path.exists():
            raise SandboxError(f"fixture not found: {fixture_path}")
        if not fixture_path.is_dir():
            raise SandboxError(f"fixture is not a directory: {fixture_path}")

        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cbs-sandbox-"))
        if copy:
            shutil.copytree(fixture_path, tmp / "repo", symlinks=False)
            workdir = (tmp / "repo").resolve()
        else:
            # Read-only symlink to the original. Used by graders, not the agent.
            (tmp / "repo").symlink_to(fixture_path, target_is_directory=True)
            workdir = (tmp / "repo").resolve()
        return cls(workdir=workdir, _owns_tempdir=tmp)

    def resolve(self, path: str | Path) -> Path:
        """Resolve a tool-supplied path against the sandbox root.

        Rejects:
          - absolute paths (POSIX or Windows-style)
          - paths that resolve outside the workdir (e.g. "../etc/passwd")

        Returns the resolved absolute path. The path need not exist
        (write_file creates new files).
        """
        if path is None:
            raise SandboxError("path is required")
        s = str(path)
        # On Windows, `Path("/etc/passwd").is_absolute()` returns False
        # because /foo is not a Windows root. Reject leading-slash and
        # leading-backslash strings explicitly so we don't accidentally
        # resolve a POSIX-style path relative to the current drive.
        if Path(s).is_absolute() or s.startswith(("/", "\\")):
            raise SandboxError(f"absolute paths are not allowed: {path!r}")
        p = Path(s)
        # resolve() with strict=False handles "..", "." etc. without requiring
        # the file to exist (needed for write_file on new files).
        resolved = (self.workdir / p).resolve(strict=False)
        try:
            resolved.relative_to(self.workdir)
        except ValueError as e:
            raise SandboxError(
                f"path escapes sandbox: {path!r} resolves to {resolved}"
            ) from e
        return resolved

    def is_within(self, path: Path) -> bool:
        """True if `path` is inside the sandbox (after resolving)."""
        try:
            path.resolve().relative_to(self.workdir)
            return True
        except (ValueError, OSError):
            return False

    def list_files(self) -> Iterable[Path]:
        """All files under the workdir, relative to it."""
        for p in self.workdir.rglob("*"):
            if p.is_file():
                yield p.relative_to(self.workdir)

    def cleanup(self) -> None:
        """Release the underlying temp dir. Idempotent."""
        if self._owns_tempdir is not None and self._owns_tempdir.exists():
            shutil.rmtree(self._owns_tempdir, ignore_errors=True)
        self._owns_tempdir = None

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *_: object) -> None:
        self.cleanup()

    def __del__(self) -> None:  # pragma: no cover - best-effort
        import contextlib
        with contextlib.suppress(Exception):
            self.cleanup()
