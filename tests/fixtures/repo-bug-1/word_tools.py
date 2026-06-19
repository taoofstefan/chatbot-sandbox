"""Tiny Python project for the failing-test-fix case.

The source has an off-by-one bug. The test asserts the correct
behavior. `pytest` fails. The agent's job: read the code, find the
bug, fix it, verify.

This file is the *fixture source* — the agent will see a copy of it
in its sandbox. Don't change it in ways that make the bug
non-obvious.
"""

from __future__ import annotations


def count_r_in_word(word: str) -> int:
    """Return the number of lowercase 'r' characters in `word`."""
    count = 0
    for ch in word:
        if ch == "r":
            count += 1
    return count


def count_total_letters(word: str) -> int:
    return len(word)
