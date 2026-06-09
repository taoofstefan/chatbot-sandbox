"""Ollama backend (HTTP).

Supports both unauthenticated local Ollama and Ollama instances fronted by
a reverse proxy that requires a Bearer token (e.g. nginx with
`auth_basic`, Cloudflare Access, LiteLLM, etc.). The API key is resolved
through the standard KeyResolver chain.
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import Backend, BackendError, ChatResponse, RunResult


class OllamaBackend(Backend):
    """Calls a local or proxied Ollama server. Uses the /api/chat endpoint."""

    supports_chat = True

    def run(self, prompt: str) -> RunResult:
        base = (self.config.base_url or "http://localhost:11434").rstrip("/")
        url = f"{base}/api/chat"
        model = self.config.model
        if not model:
            raise BackendError("ollama backend requires 'model'")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = self.resolve_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": self.config.options,
        }

        with self._time() as t:
            try:
                with httpx.Client(timeout=self.config.timeout) as client:
                    resp = client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPError as e:
                return RunResult(error=f"ollama: {e}", latency_ms=t.elapsed_ms, model=model)
            except Exception as e:  # unexpected (e.g. json decode)
                return RunResult(
                    error=f"ollama: {e}",
                    latency_ms=t.elapsed_ms,
                    model=model,
                )

        message = (data.get("message") or {}).get("content", "")
        prompt_tokens = data.get("prompt_eval_count") or 0
        eval_tokens = data.get("eval_count") or 0
        return RunResult(
            output=message,
            latency_ms=t.elapsed_ms,
            input_tokens=int(prompt_tokens) if prompt_tokens else None,
            output_tokens=int(eval_tokens) if eval_tokens else None,
            model=model,
            raw=data,
        )

    def chat(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        base = (self.config.base_url or "http://localhost:11434").rstrip("/")
        url = f"{base}/api/chat"
        model = self.config.model
        if not model:
            raise BackendError("ollama backend requires 'model'")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        key = self.resolve_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": self.config.options,
        }
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=self.config.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message") or {}
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []
        # Normalize to the shape the agent driver expects:
        # [{"name": "...", "arguments": {...}}, ...]
        tool_calls: list[dict[str, object]] = []
        for c in raw_calls:
            fn = c.get("function") if isinstance(c, dict) else None
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            args = fn.get("arguments", {})
            # Ollama returns arguments as a dict; other backends may
            # return a JSON string. Handle both.
            if isinstance(args, str):
                import json
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append({"name": name, "arguments": args})
        return ChatResponse(content=content, tool_calls=tool_calls, raw=data)
