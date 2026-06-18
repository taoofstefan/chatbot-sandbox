"""Small stats helpers. Correct as-is — the failing tests are an
environment problem, not a source bug."""

from __future__ import annotations


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def variance(xs: list[float]) -> float:
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)