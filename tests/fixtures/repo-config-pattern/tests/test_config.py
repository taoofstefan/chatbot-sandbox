"""Tests for Config.from_dict, including the timeout_ms field the agent must
add."""

from __future__ import annotations

from config import Config


def test_defaults() -> None:
    c = Config.from_dict({})
    assert c.host == "localhost"
    assert c.port == 8080
    assert c.retries == 3
    assert c.timeout_ms == 5000


def test_override_timeout() -> None:
    c = Config.from_dict({"timeout_ms": 1000})
    assert c.timeout_ms == 1000


def test_override_host() -> None:
    c = Config.from_dict({"host": "example.com"})
    assert c.host == "example.com"
    # other fields keep their defaults
    assert c.port == 8080
    assert c.timeout_ms == 5000