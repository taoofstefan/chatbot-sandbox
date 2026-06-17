# Privacy

Benchmark results, prompts, agent logs, and model outputs captured by this
tool can contain private prompts, copied work material, or other people's
data. The default `.gitignore` keeps local runs, databases, exports, reports,
transcripts, and `*.local.yaml` overrides out of version control — but
`.gitignore` cannot protect anything you explicitly `git add`.

## The one rule

**Public examples must be synthetic only.**

Anything committed to this repository — example configs under `examples/`,
README snippets, test fixtures, exported reports, screenshots, or any prompt
text or model output that ships with the repo — must be fabricated for
demonstration and must never contain:

- real prompts or instructions you were given by someone else,
- real model outputs, agent logs, or transcripts,
- real data, code, or documents from your work,
- real API keys, tokens, or credentials of any kind.

If you need realistic-looking content for an example, write it yourself from
scratch. If you are unsure whether something is synthetic, do not commit it.