"""Tests for the HTTP backends using respx to mock the wire.

Acceptance from TODO #11: every backend has a happy-path test and a
401/500 error test. We also assert token-counting fields are parsed
where applicable.
"""

from __future__ import annotations

import httpx
import respx

from chatbot_sandbox.backends import build_backend
from chatbot_sandbox.config import BackendConfig
from chatbot_sandbox.secrets import KeyResolver


def _cfg(type_: str, **overrides: object) -> BackendConfig:
    base: dict[str, object] = {
        "name": f"{type_}-test",
        "type": type_,
        "model": "test-model",
        "base_url": "https://api.example.com",
        "api_key": "sk-test",
        "timeout": 5.0,
    }
    base.update(overrides)
    return BackendConfig.model_validate(base)


def _build(cfg: BackendConfig):
    """Build a backend with a resolver that exposes the inline api_key."""
    return build_backend(cfg, key_resolver=KeyResolver())


def test_ollama_happy_path() -> None:
    cfg = _cfg("ollama", base_url="https://ollama.example.com")
    backend = _build(cfg)
    with respx.mock(base_url="https://ollama.example.com") as router:
        router.post("/api/chat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "model": "test-model",
                    "message": {"role": "assistant", "content": "hi back"},
                    "prompt_eval_count": 7,
                    "eval_count": 3,
                },
            )
        )
        result = backend.run("hello")
    assert result.error is None
    assert result.output == "hi back"
    assert result.input_tokens == 7
    assert result.output_tokens == 3


def test_ollama_500_returns_error() -> None:
    cfg = _cfg("ollama", base_url="https://ollama.example.com")
    backend = _build(cfg)
    with respx.mock(base_url="https://ollama.example.com") as router:
        router.post("/api/chat").mock(return_value=httpx.Response(500, text="boom"))
        result = backend.run("hello")
    assert result.error is not None
    assert "ollama" in result.error


def test_ollama_unauthorized_returns_error() -> None:
    cfg = _cfg("ollama", base_url="https://ollama.example.com", api_key="bad")
    backend = _build(cfg)
    with respx.mock(base_url="https://ollama.example.com") as router:
        router.post("/api/chat").mock(return_value=httpx.Response(401, text="no"))
        result = backend.run("hello")
    assert result.error is not None
    assert "ollama" in result.error


def test_openai_happy_path() -> None:
    cfg = _cfg("openai", base_url="https://api.openai.com/v1")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "hello there"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 4,
                        "total_tokens": 16,
                    },
                },
            )
        )
        result = backend.run("hi")
    assert result.error is None
    assert result.output == "hello there"
    assert result.input_tokens == 12
    assert result.output_tokens == 4


def test_openai_401_returns_error() -> None:
    cfg = _cfg("openai", base_url="https://api.openai.com/v1", api_key="bad")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                401,
                json={"error": {"message": "invalid api key", "type": "auth"}},
            )
        )
        result = backend.run("hi")
    assert result.error is not None
    assert "openai" in result.error


def test_openai_500_returns_error() -> None:
    cfg = _cfg("openai", base_url="https://api.openai.com/v1")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(500, text="oops")
        )
        result = backend.run("hi")
    assert result.error is not None
    assert "openai" in result.error


def test_anthropic_happy_path() -> None:
    cfg = _cfg("anthropic", base_url="https://api.anthropic.com")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.anthropic.com") as router:
        router.route().mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 9, "output_tokens": 2},
                },
            )
        )
        result = backend.run("hi")
    assert result.error is None
    assert result.output == "ok"
    assert result.input_tokens == 9
    assert result.output_tokens == 2


def test_anthropic_401_returns_error() -> None:
    cfg = _cfg("anthropic", base_url="https://api.anthropic.com", api_key="bad")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.anthropic.com") as router:
        router.route().mock(
            return_value=httpx.Response(
                401,
                json={"type": "error", "error": {"type": "authentication_error"}},
            )
        )
        result = backend.run("hi")
    assert result.error is not None
    assert "anthropic" in result.error


def test_anthropic_500_returns_error() -> None:
    cfg = _cfg("anthropic", base_url="https://api.anthropic.com")
    backend = _build(cfg)
    with respx.mock(base_url="https://api.anthropic.com") as router:
        router.route().mock(return_value=httpx.Response(500, text="oops"))
        result = backend.run("hi")
    assert result.error is not None
    assert "anthropic" in result.error
