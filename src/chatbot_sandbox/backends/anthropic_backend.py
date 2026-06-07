"""Anthropic backend."""

from __future__ import annotations

from anthropic import Anthropic

from .base import Backend, BackendError, RunResult


class AnthropicBackend(Backend):
    def _client(self) -> Anthropic:
        key = self.resolve_key()
        if not key:
            raise BackendError(
                "anthropic backend requires an API key (set api_key, "
                "api_key_env + env var, or --api-key override)"
            )
        kwargs: dict[str, object] = {"api_key": key, "timeout": self.config.timeout}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return Anthropic(**kwargs)  # type: ignore[arg-type]

    def run(self, prompt: str) -> RunResult:
        if not self.config.model:
            raise BackendError("anthropic backend requires 'model'")
        with self._time() as t:
            try:
                resp = self._client().messages.create(
                    model=self.config.model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                    **self.config.options,
                )
            except Exception as e:
                return RunResult(
                    error=f"anthropic: {e}",
                    latency_ms=t.elapsed_ms,
                    model=self.config.model,
                )

        chunks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "input_tokens", None) if usage else None
        out_tok = getattr(usage, "output_tokens", None) if usage else None
        return RunResult(
            output="".join(chunks),
            latency_ms=t.elapsed_ms,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=self.config.model,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
        )
