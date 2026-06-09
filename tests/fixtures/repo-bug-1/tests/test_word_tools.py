"""Tests for word_tools. This file is intentionally tiny so the agent
can read it on one call. The point of the fixture is: the test
fails, the source is the place to fix it.
"""

from __future__ import annotations

from word_tools import count_r_in_word, count_total_letters


def test_count_r_basic() -> None:
    assert count_r_in_word("strawberry") == 3


def test_count_r_zero() -> None:
    assert count_r_in_word("banana") == 0


def test_count_r_all() -> None:
    assert count_r_in_word("rrrr") == 4


def test_count_total() -> None:
    assert count_total_letters("hello") == 5
