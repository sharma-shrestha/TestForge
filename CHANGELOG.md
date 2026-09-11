# Changelog

All notable changes to TestForge are documented here.
Format roughly follows Keep a Changelog; versions follow semver.

## [0.5.0] - unreleased

### Architecture (breaking)
- **Removed the standalone `testforge_worker` binary.** Each test binary
  now IS a worker: it links `libtestforge_core` and calls `testforge_main()`
  from its own `main()`. This fixes the v0.4 architecture where the worker
  had an empty registry and the test binary couldn't be run directly.
- **Added `testforge_main()` entry point** in `entry.hpp` / `entry.cpp`,
  linked into `libtestforge_core`. Test binaries provide `main()` and
  delegate to `testforge_main()`.
- **Added `example_main.cpp`** shared by `example_cpp_tests` and
  `example_gpu_tests`.
- **Removed `TESTFORGE_BUILD_WORKER` CMake option** (no more standalone
  worker to build).

### C++ engine fixes
- `TestRegistry::find()` now returns `std::optional<TestCase>` instead of
  `const TestCase*`. The old version returned a pointer into a vector that
  could be reallocated by future registrations - a dangling-pointer risk.
- **Assertion recording is now consistent.** Every `ASSERT_*` and `EXPECT_*`
  macro calls `ctx.record_assertion()` unconditionally (both on pass and
  fail). Previously, `ASSERT_NE`, `ASSERT_TRUE`, `ASSERT_FALSE`, and
  `FAIL_MSG` skipped `record_assertion()`, making their failures invisible
  to the clustering algorithm.
- **Added RAII CUDA wrappers**: `DeviceBuffer<T>`, `CudaEvent`, `CudaStream`
  in `cuda_helpers.hpp`. GPU resources are freed automatically on scope
  exit, even when an assertion throws. No more `cudaFree` leaks on test
  failure.
- **Added `CHECK_CUDA(ctx, ...)` macro.** Every CUDA API call in test code
  goes through this macro. On failure, it records the CUDA error code,
  the human-readable error string, the operation, the file, and the line
  on the test context - so the failure analyst can reason about
  "cudaErrorMemoryAllocation" rather than a vague failure.

### GPU metrics (fix)
- **Structured metric transport.** The worker now emits `test_name=Foo.Bar`
  to stderr before each test, followed by `gpu_kernel_latency_ms=14.2`.
  The orchestrator parses these by test_name, not by index. The old
  index-based approach was fragile - if test A emitted a latency and test
  B didn't, the metric would be attached to test B by mistake.

### Timeout (fix)
- **Per-test subprocess timeout in the Python scheduler.** Each test now
  runs in its own subprocess invocation with its own timeout. A hung test
  is killed cleanly by `subprocess.run(timeout=...)` without affecting
  other tests. The old approach ran all tests in a shard in one subprocess
  with a 1-hour shard-level timeout, which meant a single hung test could
  block the whole shard. The C++ engine's thread-based timeout is kept
  as a secondary safety net but documented as best-effort.

### CUDA architecture (fix)
- **CMake CUDA architectures are now configurable.** Defaults to "native"
  (auto-detect the build machine's GPU). Override with
  `-DCMAKE_CUDA_ARCHITECTURES="75;80;86"` or the
  `TESTFORGE_CUDA_ARCHITECTURES` env var. The old hardcoded list
  "75;80;86;89;90" was already drifting as new GPU generations shipped.

### Regression engine (rewrite)
- **Robust baselines replace exponential smoothing.** The old algorithm
  (`new = old * 0.95 + current * 0.05`) absorbs genuine regressions over
  time: a persistent 8% slowdown becomes the new normal after enough runs.
  The new algorithm uses the median and MAD (median absolute deviation)
  of the last 20 passing runs. A regression is flagged when BOTH:
    - `current > median * (1 + threshold/100)` (percentage check), AND
    - `current > median + 3 * MAD` (statistical check)
  For the first 5 runs (< 5 samples), MAD is unreliable, so only the
  percentage check is used.
- Added `StorageBackend.get_metric_history()` to fetch the last N values
  of a metric for a test (passing runs only).

### Test selection (improvement)
- **Real graph-distance weighting.** The old code claimed "decaying by
  graph distance" but actually did a flat 1.0/0.7/0.0 mapping. The new
  code does BFS over the dependency graph to compute the actual shortest
  distance from the test's component to any changed component:
  distance 0 = 1.0, 1 = 0.7, 2 = 0.5, 3 = 0.3, 4+ = 0.1.
- **Execution cost penalty.** Added a 5th scoring factor: tests are
  penalized for being slow, so among equally-risky tests the faster ones
  run first. `cost = min(1.0, median_duration_ms / 1000.0)`, subtracted
  from the score with weight `execution_cost` (default 0.10).
- Added `SelectionWeights.execution_cost` field.

### Config
- `worker_binary` renamed to `test_binary` (with backward-compat fallback).
- Added `selection.execution_cost` weight.

### Tests
- Added 7 new tests for graph distance + execution cost (total: 35).
- Fixed `PytestCollectionWarning` by adding `__test__ = False` to
  `TestSpec` (pytest was trying to collect it as a test class because
  the name starts with "Test").

## [0.4.0] - 2024-09-XX (internal)

### Added
- LLM-backed failure analyst behind `--assistant` flag.
- `testforge benchmark` subcommand.
- `testforge init` scaffolds a `.testforge/` config.
- Dependency graph reads `depends_on` from test metadata YAML.
- Stack-trace normalization before hashing.
- SQLite storage backend (default, zero-config).
- HTML report renderer.

### Known issues (fixed in 0.5.0)
- `example_cpp_tests` failed to link because it had no `main()`.
- `testforge_worker` had an empty registry (architectural disconnect).
- `TestRegistry::find()` returned a pointer into a vector.
- Assertion recording was inconsistent across macros.
- GPU metrics were parsed by index, not by test name.
- Baseline algorithm used exponential smoothing (absorbed regressions).
- Test selection claimed graph-distance weighting but didn't do it.
- CMake hardcoded CUDA architectures.
- `TestSpec` triggered PytestCollectionWarning.
