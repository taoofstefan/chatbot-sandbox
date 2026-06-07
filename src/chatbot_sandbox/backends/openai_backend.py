"""OpenAI backend (API or any OpenAI-compatible endpoint)."""

from __future__ import annotations

from openai import OpenAI

from .base import Backend, BackendError, RunResult


class OpenAIBackend(Backend):
    def _client(self) -> OpenAI:
        key = self.resolve_key() or "ollama"
        kwargs: dict[str, object] = {"api_key": key, "timeout": self.config.timeout}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        return OpenAI(**kwargs)  # type: ignore[arg-type]

    def run(self, prompt: str) -> RunResult:
        if not self.config.model:
            raise BackendError("openai backend requires 'model'")
        with self._time() as t:
            try:
                resp = self._client().chat.completions.create(
                    model=self.config.model,
                    messages=[{"role": "user", "content": prompt}],
                    **self.config.options,
                )
            except Exception as e:
                return RunResult(
                    error=f"openai: {e}",
                    latency_ms=t.elapsed_ms,
                    model=self.config.model,
                )

        msg = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", None) if usage else None
        out_tok = getattr(usage, "completion_tokens", None) if usage else None
        return RunResult(
            output=msg,
            latency_ms=t.elapsed_ms,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=self.config.model,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else {},
        )
