"""Tests for find_user_id. Only the known-email path is asserted here; the
unknown-email behavior is exercised through the callers in test_callers.py."""

from __future__ import annotations

from users import find_user_id


def test_known_alice() -> None:
    assert find_user_id("alice@example.com") == 101


def test_known_bob() -> None:
    assert find_user_id("bob@example.com") == 202


def test_known_carol() -> None:
    assert find_user_id("carol@example.com") == 303