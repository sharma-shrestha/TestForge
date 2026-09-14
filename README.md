# TestForge

**Intelligent test automation & GPU validation framework.**

TestForge is a developer-testing platform that discovers, schedules, parallelizes and
executes software and GPU tests, detects functional / flaky / performance regressions,
and uses historical run data for intelligent test selection and failure analysis.

It was built as a personal project to explore what a real internal testing platform
looks like end-to-end: from a C++ test engine, through a Python orchestration layer,
to GPU correctness/perf validation on CUDA workloads, all wired up to a historical
database and a small dashboard.

---

## Architecture

The key architectural decision (fixed in v0.5): **every test binary IS a worker.**
There is no separate "testforge_worker" binary. Each test binary links
`libtestforge_core` and provides a `main()` that delegates to `testforge_main()`.
The Python orchestrator invokes the test binary directly with `--filter name1,name2`
and parses the JSON report from stdout.

```
                 Python Orchestrator
                         |
                         v
                  Test binary (example_cpp_tests, example_gpu_tests, your own)
                         |
              +----------+----------+
              |                     |
         TestForge Core         Test Registry
         (libtestforge_core)    (TEST() macro, static-init)
              |                     |
              +----------+----------+
                         v
                    TestRunner
                         |
                         v
              JSON report on stdout
```

This means the test binary contains BOTH the test code AND the engine that
runs it. No more "worker with empty registry" problem.

## High Level Data Flow

                +------------------+
                |  testforge CLI   |
                |  (click)         |
                +--------+---------+
                         |
                         v
                +------------------+
                |  Config loader   |
                |  (.testforge/    |
                |   config.yaml)   |
                +--------+---------+
                         |
                         v
                +------------------+
                |   Discovery      |  walks filesystem, asks each test
                +--------+---------+  binary to --list itself
                         |
                         v
                +------------------+
                |   Dependency     |  if --changed-files: filter to relevant
                |   graph + select |  tests via graph + scoring
                +--------+---------+
                         |
                         v
                +------------------+
                |   Scheduler      |  groups tests by binary, spawns each
                |   (ThreadPool)   |  binary with --filter name1,name2
                +--------+---------+
                         |
            +------------+------------+
            v            v            v
       +----------+ +----------+ +----------+
       |Test Bin A| |Test Bin A| |Test Bin B|  (each is a subprocess)
       |shard 1   | |shard 2   | |shard 3   |
       +----+-----+ +----+-----+ +----+-----+
            |            |            |
            +------------+------------+
                         | JSON on stdout
                         v
                +------------------+
                |   Result         |  parse + attach GPU metrics by test_name
                |   collector      |
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │   Storage        │  SQLite / Postgres
                │   (StorageBackend)│
                └────────┬─────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       ┌────────┐   ┌────────┐   ┌────────┐
       │ Regress│   │ Flaky  │   │Cluster │
       │ detect │   │ detect │   │failure │
       └────┬───┘   └────┬───┘   └────┬───┘
            │            │            │
            └────────────┼────────────┘
                         │
                         ▼
                ┌──────────────────┐
                │   Reporter       │  terminal + HTML
                └────────┬─────────┘
                         │
                         ▼
                ┌──────────────────┐
                │   (optional)     │
                │   LLM analyst    │  OpenAI-compatible endpoint
                └──────────────────┘

---

## What's inside

```
testforge/
├── cpp/                      # C++17 test engine + test binaries
│   ├── include/testforge/    # public headers
│   ├── src/                   # engine + entry point (testforge_main)
│   └── examples/              # sample CPU + CUDA test binaries
├── python/                    # orchestration layer
│   ├── testforge/             # library code
│   └── cli/                   # testforge CLI entrypoint
├── tests/                     # pytest unit tests for the Python layer
├── db/                        # schema + migrations
├── docker/                    # worker / dashboard containers
├── docs/                      # architecture + design notes
├── examples/demo/             # the "killer demo" scenario
└── .github/workflows/         # CI
```

---

## Quickstart

### Build the C++ engine + test binary

```bash
# With CMake (preferred):
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=OFF
cmake --build build -j

# Or without CMake (g++ fallback):
python scripts/build.py
```

This produces `build/bin/example_cpp_tests` - a test binary that IS a worker.
It links `libtestforge_core` and registers tests via the `TEST()` macro.

### Install the Python CLI

```bash
cd python && pip install -e .
```

### Run

```bash
# Initialize a testforge project in the current dir
testforge init

# Discover available tests (asks each test binary to --list itself)
testforge discover

# Run all tests, parallel across N workers
testforge run --workers 8

# Run only GPU-tagged tests
testforge run --suite GPU

# Run only tests affected by changed files (uses dependency graph + history)
testforge run --changed-files src/memory/allocator.cpp

# Analyze the latest build
testforge analyze

# Pretty HTML report
testforge report --build latest --html report.html
```

---

## The demo

The headline scenario lives in `examples/demo/`. It deliberately introduces a
performance regression into a matrix-multiplication kernel, then shows TestForge
catching it using the robust regression engine (median + MAD, not exponential
smoothing):

```
Build 1-6  Math.MatrixMultiplyKnown   latency ~0.5ms   PASS  (baseline established)
Build 7    Math.MatrixMultiplyKnown   latency ~1.7ms   PERF REGRESSION +235%  FAIL
```

See `docs/demo_walkthrough.md` for the step-by-step.

Run it yourself:

```bash
./examples/demo/introduce_regression.sh
```

---

## Design notes

- **C++ core, Python orchestration.** The hot path (test execution, assertion,
  result collection) is C++ for speed and because the tests themselves are
  often C++. Everything around it - discovery, scheduling, analytics,
  reporting - is Python because that's where the ecosystem is.

- **Boring tech, aggressively.** SQLite by default. PostgreSQL when you need
  it. No Redis, no Kubernetes, no message queue. The system is small enough
  to read end-to-end in an afternoon.

- **Test binaries ARE workers.** Each test binary links `libtestforge_core`
  and calls `testforge_main()`. The orchestrator invokes the test binary
  directly. No separate worker binary with an empty registry.

- **Per-test subprocess isolation.** Each test runs in its own subprocess
  invocation. A hung test is killed by `subprocess.run(timeout=...)` without
  affecting other tests. No detached threads, no resource leaks.

- **Robust regression detection.** Baselines use median + MAD (median
  absolute deviation) of the last 20 passing runs, not exponential
  smoothing. A single outlier doesn't move the baseline; a genuine
  regression is flagged when `current > median * (1 + threshold)` AND
  `current > median + 3*MAD`.

- **Real graph-distance weighting.** Test selection scores tests by their
  BFS distance from changed components in the dependency graph:
  distance 0 = 1.0, 1 = 0.7, 2 = 0.5, 3 = 0.3, 4+ = 0.1.

- **RAII CUDA wrappers.** `DeviceBuffer<T>`, `CudaEvent`, `CudaStream`
  free GPU resources automatically, even when an assertion throws.
  `CHECK_CUDA(ctx, ...)` checks every CUDA API call and records failures
  with the full error string.

- **Rule-based failure clustering, optional LLM analyst.** Clustering
  uses stack-trace + error-signature hashing (deterministic, fast, cheap).
  The LLM analyst is optional and off by default - it talks to any
  OpenAI-compatible endpoint, and silently falls back when not configured.

- **GPU metrics degrade gracefully.** If `nvidia-smi` isn't available, or
  the CUDA test binary can't query device properties, those metric fields
  are reported as `null` rather than crashing the run.

---

## Status

Things that work end-to-end today:

- C++ engine + test binaries (CPU + CUDA)
- Python CLI: discover / run / analyze / report / benchmark / dashboard
- Dependency graph + intelligent test selection (real graph-distance weighting)
- Parallel scheduler with per-test subprocess timeout
- Functional, performance, and resource regression detection (robust: median + MAD)
- Flaky test detection with quarantine threshold
- Rule-based failure clustering
- Optional LLM-backed failure analyst
- SQLite storage, PostgreSQL backend
- HTML + terminal reports
- Single-page dashboard

Things that are partial / planned:

- Distributed workers over network (single-machine subprocess pool works today;
  protocol documented in `docs/distributed_workers.md`)
- OpenTelemetry traces (Prometheus metrics endpoint works)

---

## License

MIT. See `LICENSE`.
