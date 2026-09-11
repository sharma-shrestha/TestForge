# TestForge demo walkthrough

This document walks through the headline TestForge scenario: a developer
introduces a performance regression, TestForge catches it automatically.

You can run the demo end-to-end with:

```bash
./examples/demo/introduce_regression.sh
```

The script takes about 30 seconds on a typical laptop.

## What the demo does

1. **Builds the C++ engine** (if not already built).
2. **Establishes a baseline.** It runs the Math.MatrixMultiplyKnown test
   twice via `testforge run`, which stores a baseline latency in the
   perf_baselines table of the SQLite DB.

3. **Applies a patch** (`examples/demo/regression.patch`) to the test's
   `matmul` implementation. The patch adds a `std::this_thread::sleep_for`
   inside the hot loop - a deliberately obvious regression. In real life
   this would be something subtle: a worse memory access pattern, an
   accidental synchronization, a removed `#pragma omp parallel for`, etc.

4. **Rebuilds the worker** with the patched source.

5. **Runs `testforge run` again.** This time:
   - The test still passes functionally (the result is correct).
   - But the latency is now much higher than the stored baseline.
   - TestForge's regression detector compares current-vs-baseline, sees
     the delta exceeds the configured `perf_pct` threshold (default 10%),
     and emits a `PERF REGRESSION` entry.

6. **The build is marked failed.** The HTML report (if you pass `--html`)
   shows the regression in the Regressions table, with the baseline value,
   current value, delta percentage, and threshold.

## Why this matters

Catching functional regressions is easy - every test framework does it.
Catching *performance* regressions is harder because:

- A test that returns the right answer is "passing" by traditional metrics.
- Performance is noisy - you need a baseline + threshold, not just a
  single observation.
- The threshold has to be configurable per-metric (CPU latency, GPU
  latency, memory, etc.) because different metrics have different
  noise profiles.

TestForge handles all three by storing per-test baselines in the database
and comparing each run against them. The comparison is rule-based (not
LLM-based) because it's the kind of decision you want to be fast,
predictable, and cheap.

## The output you should see

After step 5, the terminal output includes a Regressions table:

```
Regressions
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Test                      ┃ Kind         ┃ Metric       ┃   Delta ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ Math.MatrixMultiplyKnown  │ performance  │ duration_ms  │ +XX.XX% │
└───────────────────────────┴──────────────┴──────────────┴─────────┘
```

The HTML report includes the same information in a styled table, plus
the baseline and current values side by side.

## Running the demo with CUDA

If you have a CUDA-capable machine, you can build TestForge with CUDA
support and run the same scenario against the GPU matrix multiply test
instead:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=ON
cmake --build build -j

# Establish baseline
testforge run --suite GPU

# (Edit cpp/examples/gpu_kernels.cu to add a regression - e.g. an extra
#  cudaDeviceSynchronize inside the kernel - and rebuild.)

testforge run --suite GPU
```

The flow is identical - TestForge tracks `gpu_kernel_latency_ms` as a
separate metric with its own threshold (`gpu_latency_pct`, default 10%).
