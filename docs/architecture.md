# TestForge architecture

This document describes how the pieces fit together. If you're reading the
codebase for the first time, this is the map.

## The key architectural decision (v0.5)

**Every test binary IS a worker.** There is no separate "testforge_worker"
binary. Each test binary links `libtestforge_core` and calls
`testforge_main()` from its own `main()`. The Python orchestrator invokes
the test binary directly.

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

This fixes the v0.4 problem where the worker binary had an empty registry
and the test binary couldn't be run directly.

## High-level data flow

```
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
```

## Layers and their languages

| Layer             | Language | Why                                            |
|-------------------|----------|------------------------------------------------|
| Test engine       | C++17    | Tests are often C++; same language = no FFI.   |
| Worker binary     | C++17    | Sandbox + crash isolation per process.         |
| Orchestration     | Python   | Ecosystem (psutil, click, rich, jinja2).        |
| Storage           | SQL      | SQLite (default) or PostgreSQL.                |
| Web dashboard     | Python   | FastAPI + Jinja2, single-file templates.        |
| LLM analyst       | Python   | Optional; talks to any OpenAI-compatible API.   |

## Why subprocesses, not threads

The C++ engine uses static-init-time registration via the `TEST()` macro.
Tests are baked into the binary at link time. Running them in separate
processes gives us:

1. **Crash isolation.** A SEGFAULT in one worker doesn't lose results
   from others.
2. **Clean timeout semantics.** `subprocess.run(timeout=...)` kills the
   child cleanly; in-process threads can't be cancelled.
3. **Resource isolation.** Each worker's `getrusage` reflects only its
   own tests, so per-test CPU/RSS attribution is correct.
4. **Future distributed execution.** The same JSON-over-stdout protocol
   works over a network socket with minimal changes.

## Why a separate worker binary, not just calling the engine from Python

Two reasons:

1. The engine's tests are registered at link time. Different test
   binaries (C++ tests vs CUDA tests) need different binaries.
2. Having a separate binary means the engine library can be linked
   into arbitrary test programs - third-party code, examples, etc. -
   without dragging in the orchestration layer.

## Why SQLite by default

Zero config. The database lives at `.testforge/testforge.db` and is
created on first run. For multi-machine setups (where workers run on
different hosts), switch to PostgreSQL by editing `config.yaml`:

```yaml
storage:
  backend: postgres
  dsn: postgresql://user:pass@host/testforge
```

The schema is the same; only the SQL dialect differs slightly.

## Why rule-based clustering, with an optional LLM analyst

Failure clustering is the perfect problem for rule-based logic:
- It needs to be deterministic (same failures → same clusters).
- It needs to be fast (run on every build).
- It needs to be cheap (no API calls per failure).

The LLM is added on top, *only* for the diagnosis step where natural-
language reasoning is genuinely useful. The analyst takes a cluster's
representative failure + similar past failures and returns a structured
diagnosis. It's an enhancement, never a dependency - if no endpoint is
configured, TestForge silently falls back to rule-based clustering alone.

## Test selection scoring

The scoring function is intentionally simple - four weighted factors,
configurable weights:

```
score = w_dep   * dependency_relevance        # 1.0 if in changed component,
                                              # 0.7 if depends on it, 0 otherwise
      + w_hist  * historical_failure_rate     # failures / total executions
      + w_rec   * recent_failure_frequency    # failures in last 10 runs
      + w_perf  * performance_impact           # 1.0 if ever a perf regression
```

We deliberately did *not* use an LLM for selection. Test selection is the
kind of decision where you want fast, predictable, debuggable logic -
not probabilistic ranking. The weights are tuned by experiment: run the
full suite, look at the top-K selected, see whether defects were missed.

## Distributed execution (planned)

The single-machine worker pool works today: tests are sharded across N
subprocesses on the same host. The next step is true distribution:

```
                    ┌──────────────────┐
                    │   Orchestrator   │
                    │  (HTTP server)   │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Worker A │  │ Worker B │  │ Worker C │   (different hosts)
        │ (CPU)    │  │ (GPU 0)  │  │ (GPU 1)  │
        └──────────┘  └──────────┘  └──────────┘
```

The protocol is documented in `docs/distributed_workers.md`. A reference
implementation is stubbed but not yet wired up - the priority has been
getting the single-machine flow solid first.
