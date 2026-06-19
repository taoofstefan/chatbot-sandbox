"""Export helpers: CSV, JSON, and an HTML button.

Known issue (documented for the team): export_csv does not quote fields that
contain commas, so a field like "a,b" corrupts the row. The JSON exporter and
the button builder are correct as-is.
"""

from __future__ import annotations

import csv
import json
from io import StringIO


def export_csv(rows: list[list[str]]) -> str:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    writer.writerows(rows)
    return buffer.getvalue().rstrip("\r\n")


def export_json(rows: list[dict[str, object]]) -> str:
    return json.dumps(rows)


def build_export_button_html(label: str) -> str:
    return f'<button type="button">{label}</button>'
