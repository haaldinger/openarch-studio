# Issue: default chat model (`llama3.1` 8B) is unusably slow on CPU (resolved)

## Summary
The default Studio chat model is `llama3.1` (8B). On a CPU-only host (no GPU),
grounded-answer generation is effectively unusable — on the order of **~1 token
every 160s**, so a single cited answer takes many minutes. This makes the Ask
feature appear hung during a first-run or a laptop demo.

## Environment
- Studio POC, `studio-api` → Ollama, no GPU (Apple Silicon / CPU inference).
- `STUDIO_CHAT_MODEL` default = `llama3.1`.

## Repro
1. Run the stack on a CPU-only host with the default chat model.
2. Enrich a document, go to **Ask**, submit a question.
3. The answer streams at roughly one token per ~160 seconds → practically hangs.

## Workaround (available today)
Set a lighter chat model via the existing env var (compose already honours it):

```yaml
# compose override / .env
STUDIO_CHAT_MODEL: llama3.2:3b
```

`llama3.2:3b` returns grounded, cited answers in a usable time on CPU. (`.env` is
gitignored, so this is a per-host override, not a committed default.)

## Requested change
- Ship a **lighter default** chat model (e.g. `llama3.2:3b`) so the out-of-box
  experience works on a laptop, **or**
- Clearly document a GPU requirement for the 8B default and point first-run users
  at `STUDIO_CHAT_MODEL` for CPU hosts, **or**
- Detect no-GPU at startup and fall back to the lighter model with a log line.

## Why it matters
First-run/demo experience: the single most common evaluation path is "run it on
my laptop and ask a question." With the current default that path looks broken.

## Note
The retrieval, grounding and citation logic are model-agnostic and work fine on
the lighter model — this is purely a default-sizing / documentation issue.

## Resolution
The default chat model is now `llama3.2:3b`. Set `STUDIO_CHAT_MODEL` to override
it (e.g. `llama3.1` on a GPU host).
