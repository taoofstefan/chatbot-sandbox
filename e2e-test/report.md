# Run #1 — e2e-smoke

- Started:  `2026-06-08T15:43:47.751968+00:00`
- Finished: `2026-06-08T15:44:23.411038+00:00`
- Backends: `ollama-kimi,ollama-qwen`
- Notes: first smoke run

## Summary

| Prompt | Backend | Status | Latency | In | Out | Cost |
|---|---|---|---|---|---|---|
| hello | ollama-kimi | OK | 3903ms | 15 | 149 | - |
| classify | ollama-kimi | OK | 3238ms | 28 | 68 | - |
| sum-one-line | ollama-kimi | OK | 10489ms | 29 | 659 | - |
| hello | ollama-qwen | OK | 9033ms | 17 | 668 | - |
| classify | ollama-qwen | OK | 3535ms | 30 | 241 | - |
| sum-one-line | ollama-qwen | OK | 25104ms | 32 | 2127 | - |

## hello

### ollama-kimi

`3903ms`  model: `kimi-k2.6:cloud`  tokens: 15+149

```
Hello there!
```

_Notes: both models agree_

Tags: `smoke`

### ollama-qwen

`9033ms`  model: `qwen3.5:cloud`  tokens: 17+668

```
Hello there!
```

Tags: `smoke`

## classify

### ollama-kimi

`3238ms`  model: `kimi-k2.6:cloud`  tokens: 28+68

```
Positive
```

Tags: `classification`

### ollama-qwen

`3535ms`  model: `qwen3.5:cloud`  tokens: 30+241

```
Positive
```

Tags: `classification`

## sum-one-line

### ollama-kimi

`10489ms`  model: `kimi-k2.6:cloud`  tokens: 29+659

```
The animals are all doing different things.
```

Tags: `summarization`

### ollama-qwen

`25104ms`  model: `qwen3.5:cloud`  tokens: 32+2127

```
A fox, dog, and cat perform different actions.
```

Tags: `summarization`
