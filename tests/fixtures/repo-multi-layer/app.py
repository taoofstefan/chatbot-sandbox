"""Tiny backend for the multi-layer case. Routes are registered in ROUTES and
dispatched by handle_request. (A real app would use a web framework; this
in-process router keeps the fixture dependency-free and runnable in the
sandbox.)"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import json

INDEX_HTML_PATH = Path(__file__).parent / "index.html"


def _serve_index() -> tuple[int, str]:
    return 200, INDEX_HTML_PATH.read_text()


def _serve_health() -> tuple[int, str]:
    return 200, json.dumps({"status": "ok"})


# path -> handler returning (status_code, body)
ROUTES: dict[str, Callable[[], tuple[int, str]]] = {
    "/": _serve_index,
    "/health": _serve_health,
}


def handle_request(path: str) -> tuple[int, str]:
    handler = ROUTES.get(path)
    if handler is None:
        return 404, "not found"
    return handler()
