"""Tests for the agent sandbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatbot_sandbox.agent.sandbox import Sandbox, SandboxError


def test_sandbox_from_fixture_copies_tree(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "hello.txt").write_text("hi", encoding="utf-8")
    (fixture / "sub").mkdir()
    (fixture / "sub" / "world.txt").write_text("world", encoding="utf-8")

    with Sandbox.from_fixture(fixture) as sb:
        assert (sb.workdir / "hello.txt").read_text(encoding="utf-8") == "hi"
        assert (sb.workdir / "sub" / "world.txt").read_text(encoding="utf-8") == "world"
        # The original fixture is untouched.
        assert fixture.exists()
    # Sandbox cleans up.
    assert not sb.workdir.exists()


def test_sandbox_resolve_relative_path(tmp_path: Path) -> None:
    with Sandbox.from_fixture(tmp_path) as sb:
        resolved = sb.resolve("foo/bar.txt")
        assert resolved == sb.workdir / "foo" / "bar.txt"


def test_sandbox_resolve_rejects_absolute(tmp_path: Path) -> None:
    with Sandbox.from_fixture(tmp_path) as sb:
        with pytest.raises(SandboxError) as exc:
            sb.resolve("/etc/passwd")
        assert "absolute" in str(exc.value).lower()


def test_sandbox_resolve_rejects_traversal(tmp_path: Path) -> None:
    with Sandbox.from_fixture(tmp_path) as sb:
        with pytest.raises(SandboxError) as exc:
            sb.resolve("../etc/passwd")
        assert "escapes" in str(exc.value).lower()


def test_sandbox_resolve_rejects_double_traversal(tmp_path: Path) -> None:
    with Sandbox.from_fixture(tmp_path) as sb:
        with pytest.raises(SandboxError) as exc:
            sb.resolve("foo/../../bar")
        assert "escapes" in str(exc.value).lower()


def test_sandbox_resolve_allows_nonexistent_paths(tmp_path: Path) -> None:
    """write_file needs to resolve paths that don't exist yet."""
    with Sandbox.from_fixture(tmp_path) as sb:
        new_path = sb.resolve("new/file.txt")
        assert new_path == sb.workdir / "new" / "file.txt"
        assert not new_path.exists()


def test_sandbox_is_within(tmp_path: Path) -> None:
    with Sandbox.from_fixture(tmp_path) as sb:
        assert sb.is_within(sb.workdir / "x")
        assert not sb.is_within(Path("/etc/passwd"))
        assert not sb.is_within(Path("C:/Windows/System32"))


def test_sandbox_list_files(tmp_path: Path) -> None:
    fixture = tmp_path / "fix"
    fixture.mkdir()
    (fixture / "a.py").write_text("a", encoding="utf-8")
    (fixture / "b").mkdir()
    (fixture / "b" / "c.py").write_text("c", encoding="utf-8")
    (fixture / "ignored").mkdir()  # dir, not a file

    with Sandbox.from_fixture(fixture) as sb:
        files = sorted(p.as_posix() for p in sb.list_files())
        assert files == ["a.py", "b/c.py"]


def test_sandbox_missing_fixture_raises(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="not found"):
        Sandbox.from_fixture(tmp_path / "nonexistent")


def test_sandbox_cleanup_is_idempotent(tmp_path: Path) -> None:
    sb = Sandbox.from_fixture(tmp_path)
    sb.cleanup()
    sb.cleanup()  # second call should not raise
