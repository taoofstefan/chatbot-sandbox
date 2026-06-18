"""Caller 3 of find_user_id: decides whether a user gets a perk.

Compares the id to 0, so it breaks if find_user_id returns None for unknown
emails (None > 0 raises TypeError). It only stays green if the function keeps
returning an int.
"""

from __future__ import annotations

from users import find_user_id


def has_perk(email: str) -> bool:
    uid = find_user_id(email)
    return uid > 0