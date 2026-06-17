"""Tests for the API key resolver and .env loader."""

from pathlib import Path

import pytest

from chatbot_sandbox.config import BackendConfig
from chatbot_sandbox.secrets import (
    build_resolver,
    literal_key_warning,
    load_env_file,
    parse_key_override,
    redact_backend_config,
)


def test_parse_key_override_simple() -> None:
    out = parse_key_override(["foo=sk-abc", "bar=sk-xyz"])
    assert out == {"foo": "sk-abc", "bar": "sk-xyz"}


def test_parse_key_override_empty() -> None:
    assert parse_key_override(None) == {}
    assert parse_key_override([]) == {}


def test_parse_key_override_invalid() -> None:
    with pytest.raises(ValueError):
        parse_key_override(["no-equals-sign"])


def test_load_env_file(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        "\n"
        "FOO=bar\n"
        "QUOTED=\"hello world\"\n"
        "SINGLE='single quoted'\n"
        "EMPTY=\n",
        encoding="utf-8",
    )
    out = load_env_file(f)
    assert out == {"FOO": "bar", "QUOTED": "hello world", "SINGLE": "single quoted", "EMPTY": ""}


def test_load_env_file_missing(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope") == {}


def test_resolver_priority_cli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    cfg = BackendConfig(name="oai", type="openai", model="gpt-4o-mini", api_key_env="OPENAI_API_KEY")
    r = build_resolver(overrides={"oai": "from-cli"})
    assert r.resolve(cfg) == "from-cli"


def test_resolver_priority_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "from-env")
    cfg = BackendConfig(name="oai", type="openai", model="gpt-4o-mini", api_key_env="MY_KEY")
    r = build_resolver()
    assert r.resolve(cfg) == "from-env"


def test_resolver_priority_literal() -> None:
    cfg = BackendConfig(
        name="oai",
        type="openai",
        model="gpt-4o-mini",
        api_key="literal-key",
    )
    r = build_resolver()
    assert r.resolve(cfg) == "literal-key"


def test_resolver_priority_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_TOKEN", raising=False)
    f = tmp_path / ".env"
    f.write_text("OLLAMA_TOKEN=from-file\n", encoding="utf-8")
    cfg = BackendConfig(
        name="o",
        type="ollama",
        model="llama3",
        api_key_env="OLLAMA_TOKEN",
    )
    r = build_resolver(env_file=f)
    assert r.resolve(cfg) == "from-file"


def test_resolver_env_file_does_not_override_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DUAL_KEY", "process-wins")
    f = tmp_path / ".env"
    f.write_text("DUAL_KEY=file-loses\n", encoding="utf-8")
    r = build_resolver(env_file=f)
    cfg = BackendConfig(name="x", type="openai", model="m", api_key_env="DUAL_KEY")
    assert r.resolve(cfg) == "process-wins"


def test_resolver_missing_returns_none() -> None:
    cfg = BackendConfig(name="oai", type="openai", model="gpt-4o-mini")
    assert build_resolver().resolve(cfg) is None


def test_literal_key_warning_when_present() -> None:
    cfg = BackendConfig(name="oai", type="openai", model="m", api_key="sk-secret")
    msg = literal_key_warning(cfg)
    assert msg is not None
    assert "oai" in msg
    assert "literal api_key" in msg


def test_literal_key_warning_when_absent() -> None:
    cfg = BackendConfig(name="oai", type="openai", model="m", api_key_env="OPENAI_API_KEY")
    assert literal_key_warning(cfg) is None


def test_redact_backend_config_redacts_literal_api_key() -> None:
    cfg = BackendConfig(name="oai", type="openai", model="m", api_key="sk-secret")
    snap = redact_backend_config(cfg)
    assert snap["api_key"] == "[redacted]"
    assert snap["api_key_env"] is None
    assert snap["name"] == "oai"
    assert snap["model"] == "m"


def test_redact_backend_config_keeps_api_key_env_name() -> None:
    cfg = BackendConfig(
        name="oai", type="openai", model="m", api_key="sk-secret", api_key_env="OPENAI_API_KEY"
    )
    snap = redact_backend_config(cfg)
    assert snap["api_key"] == "[redacted]"
    assert snap["api_key_env"] == "OPENAI_API_KEY"


def test_redact_backend_config_redacts_secret_option_keys() -> None:
    cfg = BackendConfig(
        name="oai",
        type="openai",
        model="m",
        options={"temperature": 0.7, "api_key": "opt-secret", "token": "t"},
    )
    snap = redact_backend_config(cfg)
    assert snap["options"]["temperature"] == 0.7
    assert snap["options"]["api_key"] == "[redacted]"
    assert snap["options"]["token"] == "[redacted]"


def test_redact_backend_config_without_api_key() -> None:
    cfg = BackendConfig(name="ollama", type="ollama", model="llama3")
    snap = redact_backend_config(cfg)
    assert snap["api_key"] is None
    assert snap["name"] == "ollama"
