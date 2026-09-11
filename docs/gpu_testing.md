# GPU testing in TestForge

This document describes how TestForge handles GPU tests: what's supported,
how metrics are collected, and how regressions are detected.

## What we test on the GPU

TestForge ships sample CUDA tests for the workloads you'd typically care
about validating:

| Test                | What it checks                                              |
|---------------------|-------------------------------------------------------------|
| `GPU.VectorAdd`     | Element-wise addition. Simple correctness + first perf canary.|
| `GPU.MatrixMultiply`| Classic GEMM. Catches most memory-access regressions.       |
| `GPU.MemoryStress`  | Repeated alloc/free. Catches allocator leaks and OOM.       |
| `GPU.Reduction`     | Parallel reduction. Catches sync bugs and warp divergence.   |
| `GPU.Convolution`   | (Planned.) Sliding-window kernel.                           |
| `GPU.Inference`     | (Planned.) Small transformer block, end-to-end latency.      |

Each GPU test follows the same template:

1. Build input data on the host.
2. Allocate device memory, copy inputs over.
3. Time the kernel with `cudaEvent_t` pairs.
4. Copy the result back.
5. Compare against a CPU reference implementation.
6. Assert near-equality within a tolerance.
7. Print `gpu_kernel_latency_ms=X` to stderr - TestForge parses this and
   attaches it to the test result.

## Metrics we collect

For each GPU test run:

| Metric                  | Source              | Notes                          |
|-------------------------|---------------------|--------------------------------|
| `gpu_kernel_latency_ms` | `cudaEventElapsedTime` | Inside the test binary.    |
| `gpu_utilization_pct`  | `nvidia-smi`        | Polled by the orchestrator.    |
| `gpu_memory_used_mb`   | `nvidia-smi`        | Polled by the orchestrator.    |
| `gpu_device_name`      | `nvidia-smi`        | For reporting.                 |
| `temperature_c`        | `nvidia-smi`        | Optional.                      |
| `power_w`              | `nvidia-smi`        | Optional.                      |

If `nvidia-smi` isn't available (e.g. CI runner without GPU), all the
smi-sourced metrics are reported as `null`. The kernel latency is still
collected as long as the test binary can call `cudaEvent*`.

## Regression detection on GPU metrics

Each GPU metric is tracked with its own baseline, exactly like the CPU
metrics. Default thresholds (configurable in `config.yaml`):

| Metric                  | Default threshold |
|-------------------------|-------------------|
| `gpu_kernel_latency_ms` | +10% vs baseline  |
| `gpu_memory_used_mb`   | +25% vs baseline  |
| `duration_ms` (overall) | +10% vs baseline  |

When a metric drifts beyond its threshold, TestForge emits a regression
entry and the build fails. The first time a test runs, there's no
baseline - TestForge stores the observed value as the baseline without
flagging.

Baselines are updated lazily on every passing run, with a low-pass filter
to absorb small drift without alerting:

```
new_baseline = baseline * 0.95 + current * 0.05
```

This means a 5% permanent slowdown won't trigger an alert immediately,
but will over time. If you want to reset a baseline (e.g. after a
deliberate perf-improving change), delete the row from
`perf_baselines` and let TestForge re-learn.

## CPU-vs-GPU comparison testing

The CPU and GPU test binaries share the same workload definitions
(matrix multiply, dot product, reduction), so you can directly compare:

- **Correctness**: does the GPU result match the CPU reference within
  tolerance? (Useful for catching non-deterministic floating-point
  issues - e.g. atomic-add ordering.)
- **Performance**: how much faster is the GPU? If the GPU ever becomes
  *slower* than the CPU, something is very wrong.

Both checks happen automatically when you run the full suite -
TestForge reports both `duration_ms` (CPU-side wall time) and
`gpu_kernel_latency_ms` (kernel-only time) for each GPU test.

## Building with CUDA

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=ON
cmake --build build -j
```

Without `-DTESTFORGE_ENABLE_CUDA=ON`, the CUDA tests are compiled as
"skipped" stubs that emit a clear failure message. This lets the same
codebase build on machines without a CUDA toolkit, which is useful for
developer laptops and CPU-only CI.

## Running GPU tests on a machine without a GPU

If you try to run a GPU test binary on a machine without a GPU driver,
CUDA calls will fail with `cudaErrorDevicesUnavailable`. TestForge will
report the test as failed with the CUDA error string in the failure
message - which is exactly what you want. The framework itself doesn't
crash, and other tests in the suite continue to run.

For CI, the recommended pattern is:

- CPU CI runs on every push (no GPU).
- GPU CI runs on a self-hosted runner with a GPU (see
  `.github/workflows/gpu_ci.yml`).

## Things we deliberately don't do

- **We don't try to detect CUDA errors programmatically and classify
  them.** The error string from `cudaGetErrorString` is already useful
  as a failure message; TestForge's clustering handles grouping.
- **We don't run the same kernel on multiple GPU architectures to
  compare results.** That's interesting work but it's a separate concern
  from regression detection. The current design assumes a single target
  GPU per CI run.
- **We don't profile kernels (nsight, nvprof).** That's a developer
  workflow, not a CI workflow. Profiling belongs in the developer's
  terminal, not the test report.
