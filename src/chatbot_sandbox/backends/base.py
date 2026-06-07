"""Backend base class and result type."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import BackendConfig


class BackendError(RuntimeError):
    """Raised when a backend fails to produce a result."""


@dataclass
class RunResult:
    """Outcome of a single prompt/backend execution."""

    output: str = ""
    error: str | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


class Backend:
    """Abstract base class for LLM backends."""

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.name = config.name
        self.model = config.model

    def run(self, prompt: str) -> RunResult:
        """Execute the prompt and return a RunResult. Must be implemented."""
        raise NotImplementedError

    # --- helpers ---

    def _time(self) -> _Timer:
        return _Timer()


class _Timer:
    def __enter__(self) -> _Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)

    @property
    def elapsed_ms(self) -> int:
        return getattr(self, "elapsed_ms_value", 0)

    @elapsed_ms.setter
    def elapsed_ms(self, value: int) -> None:
        self.elapsed_ms_value = value


def env_key(name: str | None) -> str | None:
    """Resolve an api_key_env name to its value, or None."""
    if not name:
        return None
    return os.environ.get(name)
