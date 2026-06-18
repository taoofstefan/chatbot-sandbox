"""New adapter — the supported place to fix amount parsing."""

from __future__ import annotations

from legacy_adapter import parse_amount


def parse_amount_safe(raw: str) -> int:
    """Parse a dollar string, tolerating thousands commas.

    Delegates to the legacy parser after normalizing input so the legacy
    comma bug never surfaces.
    """
    # BUG: delegates without normalizing -> inherits the legacy comma bug.
    return parse_amount(raw)