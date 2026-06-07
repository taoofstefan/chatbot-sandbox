"""Smoke tests for the CLI."""

from pathlib import Path

from typer.testing import CliRunner

from chatbot_sandbox.cli import app
from chatbot_sandbox.config import BackendSet, Prompt, PromptSet

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "chatbot-sandbox" in result.output


def test_types() -> None:
    result = runner.invoke(app, ["types"])
    assert result.exit_code == 0
    for t in ("ollama", "openai", "anthropic", "claude_cli", "codex_cli", "command"):
        assert t in result.output


def test_validate_prompts_yaml(tmp_path: Path) -> None:
    f = tmp_path / "prompts.yaml"
    f.write_text(
        "name: t\nprompts:\n  - id: a\n    text: hi\n    tags: [smoke]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--prompts", str(f)])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_validate_backends_yaml(tmp_path: Path) -> None:
    f = tmp_path / "backends.yaml"
    f.write_text(
        "backends:\n"
        "  - name: local-llama\n"
        "    type: ollama\n"
        "    model: llama3.1:8b\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--backends", str(f)])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_prompt_set_roundtrip() -> None:
    ps = PromptSet(
        name="n",
        prompts=[Prompt(id="a", text="hi", tags=["t1"]), Prompt(id="b", text="ho")],
    )
    assert ps.prompts[0].id == "a"
    assert ps.prompts[1].tags == []


def test_backend_set_find(tmp_path: Path) -> None:
    f = tmp_path / "b.yaml"
    f.write_text(
        "backends:\n"
        "  - name: a\n    type: ollama\n    model: m\n"
        "  - name: b\n    type: ollama\n    model: m\n",
        encoding="utf-8",
    )
    bs = BackendSet.from_yaml(f)
    picked = bs.find(["b", "a"])
    assert [b.name for b in picked] == ["b", "a"]
