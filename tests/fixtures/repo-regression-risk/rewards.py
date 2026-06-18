"""Caller 2 of find_user_id: computes a bonus.

Does arithmetic on the id, so it breaks if find_user_id returns None for
unknown emails (None + 1000 raises TypeError). It only stays green if the
function keeps returning an int.
"""

from __future__ import annotations

from users import find_user_id


def bonus_points(email: str) -> int:
    uid = find_user_id(email)
    return uid + 1000