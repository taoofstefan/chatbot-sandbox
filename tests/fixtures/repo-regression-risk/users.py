"""User lookup. find_user_id maps an email to a numeric user id.

Known users are listed in USERS. The function is used by three callers in
summary.py, rewards.py, and perks.py.
"""

from __future__ import annotations

USERS: dict[str, int] = {
    "alice@example.com": 101,
    "bob@example.com": 202,
    "carol@example.com": 303,
}


def find_user_id(email: str) -> int:
    """Return the numeric id for `email`.

    Unknown emails currently raise KeyError; the test suite fails because of
    it. Fix the behavior so the whole suite passes.
    """
    # BUG: raises KeyError on unknown emails.
    return USERS[email]