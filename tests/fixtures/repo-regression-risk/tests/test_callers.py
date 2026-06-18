"""Tests for the three callers of find_user_id, including the unknown-email
path. summary tolerates a falsy id; rewards and perks require an int."""

from __future__ import annotations

from perks import has_perk
from rewards import bonus_points
from summary import format_greeting


def test_greeting_known() -> None:
    assert format_greeting("alice@example.com") == "User #101"


def test_greeting_unknown() -> None:
    assert format_greeting("nobody@example.com") == "Guest"


def test_bonus_known() -> None:
    assert bonus_points("alice@example.com") == 1101


def test_bonus_unknown() -> None:
    # id 0 (unknown user) + 1000
    assert bonus_points("nobody@example.com") == 1000


def test_perk_known() -> None:
    assert has_perk("alice@example.com") is True


def test_perk_unknown() -> None:
    # 0 > 0 is False
    assert has_perk("nobody@example.com") is False