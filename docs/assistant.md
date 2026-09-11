# Optional: LLM-backed failure analyst

TestForge includes an optional LLM-backed failure analyst that runs alongside
the rule-based failure clustering. It is off by default and never a hard
dependency - if no endpoint is configured, TestForge silently uses rule-based
clustering alone.

## What it does

When enabled (via `testforge run --assistant` or `testforge analyze --assistant`),
the analyst takes the representative failure from each cluster, plus the top-5
most similar historical failures from storage, and asks an LLM to:

1. Diagnose the most likely root cause.
2. Estimate confidence (0.0 - 1.0).
3. Suggest concrete investigation steps.

The output is structured JSON, written into the build report next to the
rule-based cluster, clearly labeled as "assistant analysis".

## Why an LLM here (and not elsewhere)

Test selection, scheduling, regression thresholds - those are decisions where
you want fast, predictable, debuggable logic. An LLM is none of those things.

Failure diagnosis is different. It's a natural-language reasoning task over
structured inputs (stack trace + error message + environment + similar past
failures). That's exactly where LLMs earn their keep - and exactly where
rule-based logic struggles.

So we keep the LLM in one place: post-hoc diagnosis, where it's an enhancement
to the rule-based cluster, never a dependency.

## Configuration

In `.testforge/config.yaml`:

```yaml
assistant:
  enabled: true
  base_url: "https://api.example.com/v1"      # any OpenAI-compatible endpoint
  api_key_env: "TESTFORGE_ASSISTANT_KEY"      # name of env var with the API key
  model: "gpt-4o-mini"                         # or any model your endpoint serves
  max_tokens: 600
  timeout_seconds: 30.0
```

Then set the API key as an environment variable:

```bash
export TESTFORGE_ASSISTANT_KEY="sk-..."
testforge run --assistant
```

## What the analyst sees

The prompt sent to the LLM contains:

- The test name and component.
- The failure message (truncated to ~2k chars).
- The stack trace (truncated similarly).
- The test's tags.
- The top-5 most similar historical failures (by signature similarity),
  with their test name, build ID, and a truncated failure message.

It does *not* contain:

- Source code (TestForge doesn't have access to the user's repo beyond
  what the test binaries expose).
- Internal context from the test framework.
- Anything from the rule-based cluster - the analyst runs independently
  and its output is presented alongside the rule-based clusters, not
  derived from them.

## What it returns

The LLM is instructed to return strict JSON:

```json
{
  "likely_cause": "GPU memory allocation failed because the test requested
                   more memory than the device has available.",
  "confidence": 0.87,
  "related_failures": ["GPU.MemoryStress#381", "GPU.MemoryStress#402"],
  "suggested_investigation": [
    "Check the matrix size in gpu_kernels.cu - recent commit X increased
     the default from 256 to 2048.",
    "Verify the device's free memory before the allocation using
     cudaMemGetInfo.",
    "Consider reducing the matrix size or batching the allocation."
  ]
}
```

We tolerate surrounding prose by extracting the first `{...}` block, but
the model is instructed to emit JSON only.

## When to skip it

Don't enable the assistant if:

- You don't have an OpenAI-compatible endpoint available. (TestForge
  falls back silently, so this isn't an error - it's a no-op.)
- Your tests have sensitive failure messages that shouldn't be sent to
  a third-party API. (Configure a local endpoint instead.)
- Your build is latency-sensitive - the analyst adds ~5-10 seconds per
  cluster, which can add up on a build with many clusters.
