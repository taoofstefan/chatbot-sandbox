"""Backend base class and result type."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..config import BackendConfig

if TYPE_CHECKING:
    from ..secrets import KeyResolver


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

    #: Whether this backend supports multi-turn chat with tool calls.
    #: Subclasses set this to True if they implement `chat()`.
    supports_chat: bool = False

    def __init__(
        self,
        config: BackendConfig,
        key_resolver: KeyResolver | None = None,
    ) -> None:
        self.config = config
        self.name = config.name
        self.model = config.model
        self.keys = key_resolver

    def resolve_key(self) -> str | None:
        if self.keys is None:
            return None
        return self.keys.resolve(self.config)

    def run(self, prompt: str) -> RunResult:
        """Execute the prompt and return a RunResult. Must be implemented."""
        raise NotImplementedError

    def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        """Multi-turn chat. Default raises NotImplementedError.

        Subclasses that set `supports_chat = True` must override this.
        `messages` is the chat history (role/content/dict-shaped items).
        `tools` is a list of JSON-Schema tool definitions; None means no
        tools (pure chat). The returned `ChatResponse` carries the
        assistant message and any parsed tool calls.
        """
        raise NotImplementedError("this backend does not implement chat()")

    def _time(self) -> _Timer:
        return _Timer()


@dataclass
class ChatResponse:
    """Outcome of a `Backend.chat()` call.

    Mirrors the agent-side `ModelResponse` but stays in the backends
    package so we don't create a circular import. The driver converts
    one into the other.
    """

    content: str = ""
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)


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
