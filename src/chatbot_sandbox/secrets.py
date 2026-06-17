"""Flexible API key resolution.

Priority order (highest wins):
  1. `overrides` dict passed at call time (e.g. from --api-key on the CLI)
  2. process environment variable named in `api_key_env`
  3. literal value of `api_key` in backend config
  4. None

A `.env` file is loaded once at CLI startup, BEFORE this module is queried, so
env-var based keys work transparently.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BackendConfig


@dataclass
class KeyResolver:
    """Holds per-run overrides and resolves keys for backends."""

    overrides: dict[str, str] = field(default_factory=dict)
    extra_env: dict[str, str] = field(default_factory=dict)

    def resolve(self, cfg: BackendConfig) -> str | None:
        """Return an API key for the given backend, or None."""
        if cfg.name in self.overrides:
            return self.overrides[cfg.name]

        if cfg.api_key_env:
            value = self._lookup(cfg.api_key_env)
            if value:
                return value

        if cfg.api_key:
            return cfg.api_key

        return None

    def _lookup(self, name: str) -> str | None:
        # Process env always wins; .env file is the fallback.
        if name in os.environ:
            return os.environ[name]
        return self.extra_env.get(name)

    def names_resolved(self) -> dict[str, str | None]:
        """Return a dict backend-name -> resolved key for all overrides."""
        return dict(self.overrides)


def load_env_file(path: Path) -> dict[str, str]:
    """Read a .env file into a dict. Does not mutate os.environ.

    Lines starting with '#' and blank lines are ignored. Format: KEY=VALUE.
    Values may be quoted with single or double quotes; surrounding whitespace
    is stripped. Existing environment variables are NOT overridden.
    """
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        parsed[key] = value
    return parsed


def apply_env_file(path: Path) -> dict[str, str]:
    """Load a .env file and merge values into os.environ (existing keys win)."""
    loaded = load_env_file(path)
    for k, v in loaded.items():
        os.environ.setdefault(k, v)
    return loaded


def parse_key_override(values: list[str] | None) -> dict[str, str]:
    """Parse `--api-key backend=value` style args into a {backend: key} map."""
    if not values:
        return {}
    out: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(
                f"--api-key must be in the form backend=key, got: {item!r}"
            )
        name, _, key = item.partition("=")
        name = name.strip()
        key = key.strip()
        if not name or not key:
            raise ValueError(f"--api-key must be in the form backend=key, got: {item!r}")
        out[name] = key
    return out


def build_resolver(
    overrides: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> KeyResolver:
    """Construct a resolver. If env_file is given, load it (without overriding
    existing process env). The loaded values are visible for `api_key_env`
    lookups but won't replace any value already in os.environ."""
    extra: dict[str, str] = {}
    if env_file is not None:
        extra = load_env_file(env_file)
        for k, v in extra.items():
            os.environ.setdefault(k, v)
    return KeyResolver(
        overrides=dict(overrides or {}),
        extra_env=extra,
    )


# Option keys (case-insensitive) treated as secrets when redacting a backend
# config snapshot. The dedicated `api_key` field is always redacted; this covers
# the case where a key is passed through the free-form `options` dict instead.
_SECRET_OPTION_KEYS = frozenset(
    {"api_key", "apikey", "api_token", "secret", "token", "password"}
)


def literal_key_warning(cfg: BackendConfig) -> str | None:
    """Return a warning message if ``cfg`` embeds a literal api_key, else None.

    A literal key in a config file is a secret at rest and ends up in git if
    the file is tracked; prefer ``api_key_env`` and load the value from the
    environment or a ``.env`` file.
    """
    if cfg.api_key:
        return (
            f"backend {cfg.name!r} embeds a literal api_key in config; prefer "
            "api_key_env and load the value from the environment or a .env file"
        )
    return None


def redact_backend_config(cfg: BackendConfig) -> dict[str, Any]:
    """Return a JSON-serializable snapshot of ``cfg`` with secrets removed.

    The full config (type, model, base_url, options, costs, timeout, and the
    ``api_key_env`` *name*) is kept so a run can be reproduced; the literal
    ``api_key`` value and any secret-named keys in ``options`` are replaced with
    "[redacted]". Replay reconstructs the backend from this snapshot and
    resolves keys fresh from the environment, so no secret is ever stored.
    """
    data: dict[str, Any] = cfg.model_dump(mode="json")
    if data.get("api_key"):
        data["api_key"] = "[redacted]"
    options = data.get("options")
    if isinstance(options, dict):
        data["options"] = {
            key: ("[redacted]" if key.lower() in _SECRET_OPTION_KEYS else value)
            for key, value in options.items()
        }
    return data
