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
        # BUG: this returns *before* the last character is checked.
        # The original implementation had a return here, mistakenly
        # placed during a refactor. The fix is to remove this early
        # return.
    return 0  # and this should be `return count`.


def count_total_letters(word: str) -> int:
    return len(word)
