"""Export helpers: CSV, JSON, and an HTML button.

Known issue (documented for the team): export_csv does not quote fields that
contain commas, so a field like "a,b" corrupts the row. The JSON exporter and
the button builder are correct as-is.
"""

from __future__ import annotations

import json


def export_csv(rows: list[list[str]]) -> str:
    # KNOWN ISSUE: no quoting — fields with commas break the output.
    return "\n".join(",".join(row) for row in rows)


def export_json(rows: list[dict[str, object]]) -> str:
    return json.dumps(rows)


def build_export_button_html(label: str) -> str:
    return f'<button type="button">{label}</button>'