"""Ollama backend (HTTP).

Supports both unauthenticated local Ollama and Ollama instances fronted by
a reverse proxy that requires a Bearer token (e.g. nginx with
`auth_basic`, Cloudflare Access, LiteLLM, etc.). The API key is resolved
through the standard KeyResolver chain.
"""

from __future__ import annotations

import httpx

from .base import Backend, BackendError, RunResult


class OllamaBackend(Backend):
    """Calls a local or proxied Ollama server. Uses the /api/chat endpoint."""

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
