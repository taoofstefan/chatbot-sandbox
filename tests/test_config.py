"""Tests for the configuration models in chatbot_sandbox.config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chatbot_sandbox.config import (
    KNOWN_AGENT_TOOLS,
    AgentConfig,
    Prompt,
    PromptSet,
)

# --- AgentConfig direct ---------------------------------------------------


def test_agent_config_minimal() -> None:
    cfg = AgentConfig(tools=["read_file"])
    assert cfg.tools == ["read_file"]
    assert cfg.max_steps == 15  # default
    assert cfg.step_timeout_s == 30  # default
    assert cfg.workdir is None
    assert cfg.commit_required is False
    assert cfg.use_native_tool_calling is None  # auto-detect


def test_agent_config_full() -> None:
    cfg = AgentConfig(
        tools=["read_file", "edit_file", "run_shell"],
        max_steps=20,
        step_timeout_s=60,
        workdir="tests/fixtures/repo-bug-1",
        commit_required=True,
        use_native_tool_calling=False,
    )
    assert cfg.max_steps == 20
    assert cfg.step_timeout_s == 60
    assert cfg.workdir == "tests/fixtures/repo-bug-1"
    assert cfg.use_native_tool_calling is False


def test_agent_config_rejects_unknown_tool() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentConfig(tools=["read_file", "definitely_not_a_real_tool"])
    msg = str(exc.value)
    assert "definitely_not_a_real_tool" in msg
    assert "unknown agent tool" in msg


def test_agent_config_rejects_empty_tools() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentConfig(tools=[])
    assert "at least one tool" in str(exc.value)


def test_agent_config_rejects_zero_max_steps() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentConfig(tools=["read_file"], max_steps=0)
    assert "max_steps" in str(exc.value)


def test_agent_config_rejects_negative_max_steps() -> None:
    with pytest.raises(ValidationError) as exc:
        AgentConfig(tools=["read_file"], max_steps=-3)
    assert "max_steps" in str(exc.value)


def test_known_agent_tools_constant_lists_every_tool() -> None:
    """Guard against drift: every tool named in the design doc must be in the constant."""
    for name in (
        "list_dir",
        "read_file",
        "edit_file",
        "write_file",
        "search_files",
        "run_shell",
        "draft_message",
        "approve_message",
        "send_message",
    ):
        assert name in KNOWN_AGENT_TOOLS


# --- Prompt integration ---------------------------------------------------


def test_prompt_without_agent_field_has_none() -> None:
    """Backwards-compat: prompts without `agent:` keep working."""
    p = Prompt(id="hello", text="say hi")
    assert p.agent is None


def test_prompt_with_valid_agent_config_loads() -> None:
    p = Prompt(
        id="fix-bug",
        text="fix the bug",
        agent=AgentConfig(tools=["read_file", "edit_file"], max_steps=10),
    )
    assert p.agent is not None
    assert p.agent.tools == ["read_file", "edit_file"]
    assert p.agent.max_steps == 10


def test_prompt_agent_field_rejects_unknown_tool() -> None:
    """The Prompt-level guard surfaces the same error as AgentConfig direct."""
    with pytest.raises(ValidationError) as exc:
        Prompt(
            id="x",
            text="x",
            agent=AgentConfig(tools=["not_a_tool"]),  # type: ignore[arg-type]
        )
    assert "not_a_tool" in str(exc.value)


# --- PromptSet / YAML round-trip ------------------------------------------


def test_promptset_yaml_round_trip_with_agent(tmp_path) -> None:
    """Loading a YAML file with an `agent:` block preserves it."""
    f = tmp_path / "prompts.yaml"
    f.write_text(
        "name: t\n"
        "prompts:\n"
        "  - id: fix-bug\n"
        "    text: fix it\n"
        "    agent:\n"
        "      tools: [read_file, edit_file]\n"
        "      max_steps: 12\n"
        "      workdir: tests/fixtures/repo-x\n",
        encoding="utf-8",
    )
    pset = PromptSet.from_yaml(f)
    assert len(pset.prompts) == 1
    p = pset.prompts[0]
    assert p.id == "fix-bug"
    assert p.agent is not None
    assert p.agent.tools == ["read_file", "edit_file"]
    assert p.agent.max_steps == 12
    assert p.agent.workdir == "tests/fixtures/repo-x"


def test_promptset_yaml_without_agent_field_still_loads(tmp_path) -> None:
    """Existing prompts.yaml files (no `agent:`) must continue to load."""
    f = tmp_path / "prompts.yaml"
    f.write_text(
        "name: t\n"
        "prompts:\n"
        "  - id: hello\n"
        "    text: hi\n"
        "    tags: [smoke]\n",
        encoding="utf-8",
    )
    pset = PromptSet.from_yaml(f)
    assert pset.prompts[0].agent is None


def test_promptset_yaml_rejects_bad_agent_block(tmp_path) -> None:
    """An unknown tool in the YAML gives a clear error at load time."""
    f = tmp_path / "prompts.yaml"
    f.write_text(
        "name: t\n"
        "prompts:\n"
        "  - id: x\n"
        "    text: x\n"
        "    agent:\n"
        "      tools: [totally_made_up]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        PromptSet.from_yaml(f)
    assert "totally_made_up" in str(exc.value)
