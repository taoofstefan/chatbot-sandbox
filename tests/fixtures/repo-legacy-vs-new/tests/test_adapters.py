"""Tests for new_adapter. The legacy module is frozen; the fix belongs here."""

from __future__ import annotations

from new_adapter import parse_amount_safe


def test_plain() -> None:
    assert parse_amount_safe("$100") == 100


def test_with_commas() -> None:
    assert parse_amount_safe("$1,234") == 1234


def test_large() -> None:
    assert parse_amount_safe("$1,000,000") == 1_000_000