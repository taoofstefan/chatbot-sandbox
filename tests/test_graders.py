"""Tests for the inline output graders."""

from __future__ import annotations

import pytest

from chatbot_sandbox.graders import KNOWN_CHECKS, grade, overall_passed

# --- contains ---------------------------------------------------------------


def test_contains_substring_passes() -> None:
    report = grade("The answer is 42.", {"contains": "42"})
    assert report["contains"]["passed"] is True


def test_contains_substring_case_insensitive() -> None:
    report = grade("Hello World", {"contains": "hello"})
    assert report["contains"]["passed"] is True


def test_contains_misses() -> None:
    report = grade("foo", {"contains": "bar"})
    assert report["contains"]["passed"] is False
    assert "bar" in report["contains"]["detail"]


# --- contains_all -----------------------------------------------------------


def test_contains_all_passes() -> None:
    report = grade("apples and oranges in mixed", {"contains_all": ["apples", "oranges", "mixed"]})
    assert report["contains_all"]["passed"] is True


def test_contains_all_fails_with_missing() -> None:
    report = grade("apples and oranges", {"contains_all": ["apples", "bananas"]})
    assert report["contains_all"]["passed"] is False
    assert "bananas" in report["contains_all"]["detail"]


# --- contains_def -----------------------------------------------------------


def test_contains_def_passes() -> None:
    out = "```python\ndef debounce(seconds):\n    pass\n```"
    report = grade(out, {"contains_def": "debounce"})
    assert report["contains_def"]["passed"] is True


def test_contains_def_fails_on_wrong_name() -> None:
    out = "def throttle(seconds): pass"
    report = grade(out, {"contains_def": "debounce"})
    assert report["contains_def"]["passed"] is False


def test_contains_def_rejects_partial_match() -> None:
    out = "def debounce_v2(s): pass"  # not exactly `debounce(`
    report = grade(out, {"contains_def": "debounce"})
    assert report["contains_def"]["passed"] is False


# --- equals -----------------------------------------------------------------


def test_equals_strict() -> None:
    report = grade("3", {"equals": "3"})
    assert report["equals"]["passed"] is True


def test_equals_strips_whitespace() -> None:
    report = grade("  3  \n", {"equals": "3"})
    assert report["equals"]["passed"] is True


def test_equals_mismatch() -> None:
    report = grade("four", {"equals": "4"})
    assert report["equals"]["passed"] is False


# --- extract_int ------------------------------------------------------------


def test_extract_int_plain() -> None:
    report = grade("3", {"extract_int": 3})
    assert report["extract_int"]["passed"] is True


def test_extract_int_in_sentence() -> None:
    report = grade("The answer is 3.", {"extract_int": 3})
    assert report["extract_int"]["passed"] is True


def test_extract_int_negative() -> None:
    report = grade("Temperature: -5C", {"extract_int": -5})
    assert report["extract_int"]["passed"] is True


def test_extract_int_missing() -> None:
    report = grade("no number here", {"extract_int": 3})
    assert report["extract_int"]["passed"] is False


def test_extract_int_mismatch() -> None:
    report = grade("3", {"extract_int": 4})
    assert report["extract_int"]["passed"] is False
    assert "3" in report["extract_int"]["detail"]


# --- json_keys --------------------------------------------------------------


def test_json_keys_bare_object() -> None:
    out = '{"name": "Jane", "age": 34, "city": "Berlin"}'
    report = grade(out, {"json_keys": ["name", "age", "city"]})
    assert report["json_keys"]["passed"] is True


def test_json_keys_fenced() -> None:
    out = "```json\n{\"name\": \"Jane\", \"age\": 34}\n```"
    report = grade(out, {"json_keys": ["name", "age"]})
    assert report["json_keys"]["passed"] is True


def test_json_keys_missing() -> None:
    out = '{"name": "Jane"}'
    report = grade(out, {"json_keys": ["name", "age", "city"]})
    assert report["json_keys"]["passed"] is False
    assert "age" in report["json_keys"]["detail"]


def test_json_keys_not_an_object() -> None:
    out = "[1, 2, 3]"
    report = grade(out, {"json_keys": ["x"]})
    assert report["json_keys"]["passed"] is False


# --- json_match -------------------------------------------------------------


def test_json_match_pass() -> None:
    out = '{"name": "Jane", "age": 34, "city": "Berlin"}'
    report = grade(out, {"json_match": {"name": "Jane", "age": 34, "city": "Berlin"}})
    assert report["json_match"]["passed"] is True


def test_json_match_mismatch() -> None:
    out = '{"name": "Jane", "age": 30}'
    report = grade(out, {"json_match": {"name": "Jane", "age": 34}})
    assert report["json_match"]["passed"] is False
    assert "age" in report["json_match"]["detail"]


# --- python_compiles --------------------------------------------------------


def test_python_compiles_passes() -> None:
    out = "def f(x):\n    return x + 1"
    report = grade(out, {"python_compiles": None})
    assert report["python_compiles"]["passed"] is True


def test_python_compiles_in_fence() -> None:
    out = "```python\ndef f(x):\n    return x + 1\n```"
    report = grade(out, {"python_compiles": None})
    assert report["python_compiles"]["passed"] is True


def test_python_compiles_fails_on_syntax_error() -> None:
    out = "def f(x) return x"  # missing colon
    report = grade(out, {"python_compiles": None})
    assert report["python_compiles"]["passed"] is False
    assert "SyntaxError" in report["python_compiles"]["detail"]


# --- python_runs ------------------------------------------------------------


def test_python_runs_passes() -> None:
    code = "def double(x):\n    return x * 2"
    verifier = "assert double(21) == 42"
    report = grade(code, {"python_runs": verifier})
    assert report["python_runs"]["passed"] is True


def test_python_runs_fails_when_verifier_raises() -> None:
    code = "def double(x):\n    return x + 2"
    verifier = "assert double(21) == 42"
    report = grade(code, {"python_runs": verifier})
    assert report["python_runs"]["passed"] is False
    assert "44" in report["python_runs"]["detail"] or "verifier" in report["python_runs"]["detail"].lower()


def test_python_runs_fails_on_runtime_error() -> None:
    code = "def boom():\n    return 1/0"
    verifier = "boom()"
    report = grade(code, {"python_runs": verifier})
    assert report["python_runs"]["passed"] is False
    assert "ZeroDivisionError" in report["python_runs"]["detail"]


# --- composite --------------------------------------------------------------


def test_grade_runs_independent_checks_and_aggregates() -> None:
    """Two distinct checks both report, and overall_passed reflects AND-semantics."""
    out = "The answer is 3."
    report = grade(out, {"contains": "answer", "extract_int": 3})
    assert set(report) == {"contains", "extract_int"}
    assert all(c["passed"] for c in report.values())
    assert overall_passed(report) is True


def test_grade_fails_overall_when_any_check_fails() -> None:
    report = grade("nope", {"contains": "yes", "contains_all": ["yes"]})
    assert overall_passed(report) is False


def test_overall_passed_uses_and_semantics() -> None:
    report = {
        "a": {"passed": True, "detail": ""},
        "b": {"passed": False, "detail": "no"},
    }
    assert overall_passed(report) is False
    report["b"]["passed"] = True
    assert overall_passed(report) is True


def test_overall_passed_empty_is_true() -> None:
    assert overall_passed({}) is True


def test_grade_unknown_check_reported_as_failure() -> None:
    report = grade("anything", {"nonsense_check": "x"})
    assert report["nonsense_check"]["passed"] is False
    assert "unknown" in report["nonsense_check"]["detail"]


def test_known_checks_constant_lists_every_check() -> None:
    for name in (
        "contains",
        "contains_all",
        "contains_def",
        "equals",
        "extract_int",
        "json_keys",
        "json_match",
        "python_compiles",
        "python_runs",
    ):
        assert name in KNOWN_CHECKS


def test_pydantic_rejects_unknown_validator_in_prompts_yaml() -> None:
    """Pydantic-level guard: the Prompt model rejects unknown validator keys."""
    from pydantic import ValidationError

    from chatbot_sandbox.config import Prompt

    with pytest.raises(ValidationError) as exc:
        Prompt(id="p", text="x", validators={"definitely_not_a_real_check": 1})
    assert "unknown validator" in str(exc.value)
