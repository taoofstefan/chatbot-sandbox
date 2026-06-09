"""Inline output graders for benchmark prompts.

Each prompt in `prompts.yaml` may carry a `validators:` mapping. Keys are
check names from `KNOWN_CHECKS`; values are the expected value or argument
list for the check. After a run, every result is graded and the outcome is
stored alongside the output in the database.

A check function has the signature `(output: str, expected: Any) -> tuple[bool, str]`
where the second element is a short human-readable detail (e.g. the matched
substring, the extracted int, or the failure reason).
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(
    r"```(?:python|py)?\s*\n(?P<code>.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def _strip_fences(text: str) -> str:
    """Return text with the first ```python ... ``` block extracted, if any.

    If no fenced code block is present, the original text is returned.
    """
    m = _FENCE_RE.search(text)
    return m.group("code") if m else text


def _parse_json_lenient(text: str) -> Any | None:
    """Try hard to find a JSON object/array in `text`. Returns None if all fails."""
    text = text.strip()
    # Direct parse first.
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    # Strip code fences and retry.
    inner = _strip_fences(text).strip()
    try:
        return json.loads(inner)
    except (ValueError, TypeError):
        pass
    # Last resort: grab the first {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        i = text.find(opener)
        j = text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i : j + 1])
            except (ValueError, TypeError):
                continue
    return None


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_contains(output: str, expected: str) -> tuple[bool, str]:
    if not isinstance(expected, str):
        return False, f"contains expects a string, got {type(expected).__name__}"
    return (expected.lower() in output.lower()), f"need substring: {expected!r}"


def _check_contains_all(output: str, expected: list[str]) -> tuple[bool, str]:
    if not isinstance(expected, list) or not all(isinstance(s, str) for s in expected):
        return False, "contains_all expects a list of strings"
    lower = output.lower()
    missing = [s for s in expected if s.lower() not in lower]
    if missing:
        return False, f"missing: {missing}"
    return True, f"all of {expected} present"


def _check_contains_def(output: str, expected: str) -> tuple[bool, str]:
    if not isinstance(expected, str):
        return False, "contains_def expects a function name (string)"
    pattern = rf"\bdef\s+{re.escape(expected)}\s*\("
    return (re.search(pattern, output) is not None), f"def {expected}(...) found"


def _check_equals(output: str, expected: Any) -> tuple[bool, str]:
    return (output.strip() == str(expected).strip()), f"equals: {expected!r}"


_INT_RE = re.compile(r"-?\d+")


def _check_extract_int(output: str, expected: int) -> tuple[bool, str]:
    if not isinstance(expected, int) or isinstance(expected, bool):
        return False, f"extract_int expects an integer, got {type(expected).__name__}"
    m = _INT_RE.search(output)
    if m is None:
        return False, "no integer found in output"
    found = int(m.group(0))
    return found == expected, f"extracted {found} (want {expected})"


def _check_json_keys(output: str, expected: list[str]) -> tuple[bool, str]:
    if not isinstance(expected, list) or not all(isinstance(s, str) for s in expected):
        return False, "json_keys expects a list of strings"
    parsed = _parse_json_lenient(output)
    if not isinstance(parsed, dict):
        return False, "output is not a JSON object"
    missing = [k for k in expected if k not in parsed]
    if missing:
        return False, f"missing keys: {missing}; got {sorted(parsed.keys())}"
    return True, f"keys present: {expected}"


def _check_json_match(output: str, expected: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(expected, dict):
        return False, "json_match expects a mapping of expected values"
    parsed = _parse_json_lenient(output)
    if not isinstance(parsed, dict):
        return False, "output is not a JSON object"
    mismatches: list[str] = []
    for k, v in expected.items():
        if k not in parsed:
            mismatches.append(f"missing key {k!r}")
        elif parsed[k] != v:
            mismatches.append(f"{k!r}: got {parsed[k]!r}, want {v!r}")
    if mismatches:
        return False, "; ".join(mismatches)
    return True, f"matched: {expected}"


def _check_python_compiles(output: str, expected: Any = None) -> tuple[bool, str]:
    code = _strip_fences(output)
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} (line {e.lineno})"
    return True, "parses as valid Python"


def _check_python_runs(output: str, expected: str) -> tuple[bool, str]:
    """Run extracted code, then run `expected` (a snippet) using exec scope.

    `expected` should be a string of Python that raises AssertionError on
    failure. The check passes iff exec succeeds with no AssertionError.
    """
    if not isinstance(expected, str):
        return False, "python_runs expects a string of Python (the verifier)"
    code = _strip_fences(output)
    scope: dict[str, Any] = {}
    try:
        exec(compile(code, "<model output>", "exec"), scope)
    except Exception as e:
        return False, f"output failed to execute: {type(e).__name__}: {e}"
    try:
        exec(compile(expected, "<verifier>", "exec"), scope)
    except AssertionError as e:
        return False, f"verifier failed: {e}"
    except Exception as e:
        return False, f"verifier errored: {type(e).__name__}: {e}"
    return True, "ran + passed verifier"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CHECKS: dict[str, Callable[[str, Any], tuple[bool, str]]] = {
    "contains": _check_contains,
    "contains_all": _check_contains_all,
    "contains_def": _check_contains_def,
    "equals": _check_equals,
    "extract_int": _check_extract_int,
    "json_keys": _check_json_keys,
    "json_match": _check_json_match,
    "python_compiles": _check_python_compiles,
    "python_runs": _check_python_runs,
}

KNOWN_CHECKS: frozenset[str] = frozenset(CHECKS)


def grade(output: str, validators: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Run every validator in `validators` against `output`.

    Returns a mapping of check-name -> {"passed": bool, "detail": str}.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, expected in validators.items():
        check = CHECKS.get(name)
        if check is None:
            out[name] = {"passed": False, "detail": f"unknown check {name!r}"}
            continue
        try:
            passed, detail = check(output, expected)
        except Exception as e:
            passed, detail = False, f"check raised {type(e).__name__}: {e}"
        out[name] = {"passed": bool(passed), "detail": detail}
    return out


def overall_passed(report: dict[str, dict[str, Any]]) -> bool:
    """A prompt passes grading iff every check passes."""
    return all(c["passed"] for c in report.values()) if report else True
