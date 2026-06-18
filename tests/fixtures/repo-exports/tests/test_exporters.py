"""Tests for the three exporters. The CSV tests use splitlines so they
tolerate either \\n or \\r\\n line endings from whichever quoting fix is
applied."""

from __future__ import annotations

from exporters import build_export_button_html, export_csv, export_json


def test_csv_plain() -> None:
    lines = export_csv([["a", "b"], ["c", "d"]]).splitlines()
    assert lines == ["a,b", "c,d"]


def test_csv_commas_quoted() -> None:
    # the known issue: a field containing a comma must be quoted
    lines = export_csv([["a,b", "c"]]).splitlines()
    assert lines == ['"a,b",c']


def test_json() -> None:
    assert export_json([{"x": 1}]) == '[{"x": 1}]'


def test_button() -> None:
    assert build_export_button_html("Go") == '<button type="button">Go</button>'