"""Ollama backend (HTTP)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import Backend, BackendError, RunResult


class OllamaBackend(Backend):
    """Calls a local Ollama server. Compatible with /api/chat."""

    def run(self, prompt: str) -> RunResult:
        base = (self.config.base_url or "http://localhost:11434").rstrip("/")
        url = f"{base}/api/chat"
        model = self.config.model
        if not model:
            raise BackendError("ollama backend requires 'model'")
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": self.config.options,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
        )

        with self._time() as t:
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                return RunResult(error=f"ollama: {e}", latency_ms=t.elapsed_ms, model=model)

        message = (payload.get("message") or {}).get("content", "")
        prompt_tokens = (payload.get("prompt_eval_count") or 0)
        eval_tokens = (payload.get("eval_count") or 0)
        return RunResult(
            output=message,
            latency_ms=t.elapsed_ms,
            input_tokens=int(prompt_tokens) if prompt_tokens else None,
            output_tokens=int(eval_tokens) if eval_tokens else None,
            model=model,
            raw=payload,
        )
