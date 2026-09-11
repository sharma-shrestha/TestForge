# SQL schema reference

This is a human-readable reference for the database schema. The actual
schema is created automatically by `SQLiteBackend` (or `PostgresBackend`)
on first connection via the `SCHEMA_SQLITE` / `SCHEMA_PG` constants in
`python/testforge/storage.py`. The two are kept in sync; if you change
one, change the other.

## Tables

### `builds`

One row per `testforge run` invocation.

| Column          | Type     | Notes                                            |
|-----------------|----------|--------------------------------------------------|
| id              | INT PK  | Auto-increment.                                  |
| started_at      | TEXT     | ISO8601 UTC.                                     |
| finished_at     | TEXT     | ISO8601 UTC, NULL until build completes.         |
| git_sha         | TEXT     | Short SHA from `git rev-parse --short HEAD`.     |
| branch          | TEXT     | From `git rev-parse --abbrev-ref HEAD`.          |
| status          | TEXT     | "passed" / "failed" / "running".                |
| worker_count    | INT      | How many parallel workers ran.                   |
| total_tests     | INT      | Total tests executed.                            |
| passed          | INT      |                                                  |
| failed          | INT      | Includes timeouts.                              |
| flaky           | INT      | Tests that passed only after retry.              |
| skipped         | INT      |                                                  |
| notes           | TEXT     | Free-form annotation.                            |

### `test_results`

One row per test per build.

| Column                  | Type     | Notes                                            |
|-------------------------|----------|--------------------------------------------------|
| id                      | INT PK  |                                                  |
| build_id               | INT FK  | → builds.id.                                      |
| test_name               | TEXT     | E.g. "Math.MatrixMultiplyKnown".                |
| suite                   | TEXT     | E.g. "Math".                                     |
| status                  | TEXT     | pass/fail/timeout/flaky/skipped.                |
| attempts                | INT      | Number of attempts (1 = first try, no retry).    |
| duration_ms             | REAL     | Wall-clock duration.                            |
| failure_message         | TEXT     |                                                  |
| failure_file            | TEXT     |                                                  |
| failure_line            | INT      |                                                  |
| error_signature        | TEXT     | Stable signature for clustering.                 |
| peak_rss_kb             | INT      | From getrusage(RUSAGE_SELF).                    |
| cpu_user_ms             | REAL     |                                                  |
| cpu_sys_ms              | REAL     |                                                  |
| gpu_utilization_pct    | REAL     | From nvidia-smi. NULL if no GPU.                |
| gpu_memory_used_mb     | INT      | From nvidia-smi.                                 |
| gpu_kernel_latency_ms   | REAL     | From cudaEventElapsedTime.                       |
| gpu_device_name         | TEXT     | E.g. "NVIDIA RTX 4090".                          |
| created_at              | TEXT     | ISO8601 UTC.                                     |

### `perf_baselines`

One row per (test_name, metric) pair. Updated lazily on each passing run.

| Column          | Type     | Notes                                            |
|-----------------|----------|--------------------------------------------------|
| test_name       | TEXT     | Composite PK with `metric`.                      |
| metric          | TEXT     | "duration_ms", "peak_rss_kb", "gpu_kernel_latency_ms", etc. |
| baseline_value  | REAL     | Low-pass-filtered moving average.                |
| sample_count    | INT      | Number of samples that contributed to baseline.  |
| updated_at      | TEXT     |                                                  |

### `failure_clusters`

One row per failure cluster per build.

| Column          | Type     | Notes                                            |
|-----------------|----------|--------------------------------------------------|
| id              | INT PK  |                                                  |
| build_id        | INT      |                                                  |
| signature       | TEXT     | The cluster's signature (hash).                  |
| component       | TEXT     | Best-guess component for the cluster.             |
| sample_message  | TEXT     | Representative failure message.                  |
| count           | INT      | Number of failures in this cluster.              |
| created_at      | TEXT     |                                                  |

## Indexes

```sql
CREATE INDEX idx_results_test  ON test_results(test_name);
CREATE INDEX idx_results_build ON test_results(build_id);
CREATE INDEX idx_results_sig   ON test_results(error_signature);
```

These cover the three most common query patterns:
- "Show me recent results for this test" (for flaky detection).
- "Show me all results in this build" (for the dashboard).
- "Show me all results with this signature" (for cluster drill-down).

## Migrations

The schema uses `CREATE TABLE IF NOT EXISTS` everywhere, so applying the
latest schema to an existing database is safe - it adds missing tables
and indexes but doesn't drop or alter anything. To change a column type
in a backwards-incompatible way, bump the schema version and add a
migration step (not yet implemented; we'll add this when the first such
change is needed).
