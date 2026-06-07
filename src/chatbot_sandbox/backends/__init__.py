"""LLM backend abstractions."""

from .base import Backend, BackendError, RunResult
from .registry import build_backend, known_types

__all__ = ["Backend", "BackendError", "RunResult", "build_backend", "known_types"]
