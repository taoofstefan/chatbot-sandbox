"""Tests for stats. These import numpy, a declared dependency that must be
present in the environment for the suite to run."""

from __future__ import annotations

import numpy as np  # declared dependency; must be installed in the env
from stats import mean, variance


def test_mean() -> None:
    assert mean([1, 2, 3]) == 2.0


def test_variance() -> None:
    assert abs(variance([1, 2, 3, 4]) - 1.25) < 1e-9


def test_matches_numpy() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    assert abs(variance(xs) - float(np.var(xs))) < 1e-9