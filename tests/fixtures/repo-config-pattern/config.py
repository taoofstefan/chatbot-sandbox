"""App configuration. Each field follows the same pattern: a module-level
DEFAULT_* constant, a dataclass field defaulting to it, and a from_dict line
that reads the key with that constant as the fallback.

To add a new setting, mirror that pattern — do not introduce a new
abstraction (no defaults registry, no pydantic, no metaclass)."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080
DEFAULT_RETRIES = 3


@dataclass
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    retries: int = DEFAULT_RETRIES

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Config:
        return cls(
            host=data.get("host", DEFAULT_HOST),
            port=data.get("port", DEFAULT_PORT),
            retries=data.get("retries", DEFAULT_RETRIES),
        )