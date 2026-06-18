"""Caller 1 of find_user_id: builds a greeting string.

Tolerates a falsy id (None or 0) by falling back to 'Guest', so it keeps
working whether find_user_id returns 0 or None for unknown emails.
"""

from __future__ import annotations

from users import find_user_id


def format_greeting(email: str) -> str:
    uid = find_user_id(email)
    if uid:
        return f"User #{uid}"
    return "Guest"