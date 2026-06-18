"""Tests for the backend router, including the /health endpoint the agent
must add."""

from __future__ import annotations

import json

from app import handle_request


def test_root() -> None:
    status, body = handle_request("/")
    assert status == 200
    assert "Demo" in body


def test_health() -> None:
    status, body = handle_request("/health")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_unknown() -> None:
    status, _body = handle_request("/nope")
    assert status == 404