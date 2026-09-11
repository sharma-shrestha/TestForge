"""PostgreSQL backend.

Same schema as SQLiteBackend, but uses psycopg2. The schema SQL is shared
with minor dialect tweaks (SERIAL instead of AUTOINCREMENT, ON CONFLICT
syntax, etc.).
"""

from __future__ import annotations

from typing import Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    raise

from .storage import StoredResult, StorageBackend


SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS builds (
    id              SERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    git_sha         TEXT,
    branch          TEXT,
    status          TEXT,
    worker_count    INTEGER,
    total_tests     INTEGER,
    passed          INTEGER,
    failed          INTEGER,
    flaky           INTEGER,
    skipped         INTEGER,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS test_results (
    id                  SERIAL PRIMARY KEY,
    build_id            INTEGER NOT NULL REFERENCES builds(id),
    test_name           TEXT NOT NULL,
    suite               TEXT,
    status              TEXT NOT NULL,
    attempts            INTEGER,
    duration_ms         DOUBLE PRECISION,
    failure_message     TEXT,
    failure_file        TEXT,
    failure_line        INTEGER,
    error_signature     TEXT,
    peak_rss_kb         BIGINT,
    cpu_user_ms         DOUBLE PRECISION,
    cpu_sys_ms          DOUBLE PRECISION,
    gpu_utilization_pct DOUBLE PRECISION,
    gpu_memory_used_mb  BIGINT,
    gpu_kernel_latency_ms DOUBLE PRECISION,
    gpu_device_name     TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_test  ON test_results(test_name);
CREATE INDEX IF NOT EXISTS idx_results_build ON test_results(build_id);
CREATE INDEX IF NOT EXISTS idx_results_sig   ON test_results(error_signature);

CREATE TABLE IF NOT EXISTS perf_baselines (
    test_name           TEXT,
    metric              TEXT,
    baseline_value      DOUBLE PRECISION,
    sample_count        INTEGER,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (test_name, metric)
);

CREATE TABLE IF NOT EXISTS failure_clusters (
    id              SERIAL PRIMARY KEY,
    build_id        INTEGER,
    signature       TEXT,
    component       TEXT,
    sample_message  TEXT,
    count           INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""


class PostgresBackend(StorageBackend):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = False
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA_PG)
        self.conn.commit()

    def create_build(self, *, git_sha: str = "", branch: str = "",
                     worker_count: int = 0, notes: str = "") -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO builds(git_sha, branch, worker_count, notes) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (git_sha, branch, worker_count, notes))
            build_id = cur.fetchone()[0]
        self.conn.commit()
        return build_id

    def finish_build(self, build_id: int, *, status: str,
                     total: int, passed: int, failed: int,
                     flaky: int, skipped: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE builds SET finished_at = NOW(), status = %s, "
                "total_tests = %s, passed = %s, failed = %s, flaky = %s, "
                "skipped = %s WHERE id = %s",
                (status, total, passed, failed, flaky, skipped, build_id))
        self.conn.commit()

    def store_result(self, build_id: int, result: StoredResult) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO test_results (
                    build_id, test_name, suite, status, attempts, duration_ms,
                    failure_message, failure_file, failure_line, error_signature,
                    peak_rss_kb, cpu_user_ms, cpu_sys_ms,
                    gpu_utilization_pct, gpu_memory_used_mb,
                    gpu_kernel_latency_ms, gpu_device_name
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (build_id, result.test_name, result.suite, result.status,
                 result.attempts, result.duration_ms,
                 result.failure_message, result.failure_file, result.failure_line,
                 result.error_signature,
                 result.peak_rss_kb, result.cpu_user_ms, result.cpu_sys_ms,
                 result.gpu_utilization_pct, result.gpu_memory_used_mb,
                 result.gpu_kernel_latency_ms, result.gpu_device_name))
        self.conn.commit()

    def get_results(self, build_id: int) -> list[StoredResult]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM test_results WHERE build_id = %s ORDER BY id",
                (build_id,))
            rows = cur.fetchall()
        return [StoredResult(**dict(r)) for r in rows]

    def recent_results(self, test_name: str, limit: int = 10) -> list[StoredResult]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM test_results WHERE test_name = %s "
                "ORDER BY id DESC LIMIT %s", (test_name, limit))
            return [StoredResult(**dict(r)) for r in cur.fetchall()]

    def total_executions(self, test_name: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM test_results WHERE test_name = %s",
                (test_name,))
            return cur.fetchone()[0]

    def total_failures(self, test_name: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM test_results WHERE test_name = %s "
                "AND status IN ('fail','timeout')", (test_name,))
            return cur.fetchone()[0]

    def has_perf_regression(self, test_name: str) -> bool:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM test_results WHERE test_name = %s "
                "AND failure_message LIKE '%%PERF REGRESSION%%'",
                (test_name,))
            return cur.fetchone()[0] > 0

    def set_perf_baseline(self, test_name: str, metric: str,
                           value: float, sample_count: int = 1) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO perf_baselines(test_name, metric, baseline_value, "
                "sample_count, updated_at) VALUES (%s, %s, %s, %s, NOW()) "
                "ON CONFLICT (test_name, metric) DO UPDATE SET "
                "baseline_value = EXCLUDED.baseline_value, "
                "sample_count = EXCLUDED.sample_count, "
                "updated_at = NOW()",
                (test_name, metric, value, sample_count))
        self.conn.commit()

    def get_perf_baseline(self, test_name: str, metric: str) -> Optional[float]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT baseline_value FROM perf_baselines "
                "WHERE test_name = %s AND metric = %s",
                (test_name, metric))
            row = cur.fetchone()
            return row[0] if row else None

    def get_metric_history(self, test_name: str, metric: str,
                          limit: int = 20) -> list[float]:
        # NOTE: %s is the psycopg2 placeholder; we can't parameterize the
        # column name, so we validate it against a whitelist to prevent SQL
        # injection. The metric parameter comes from regression.py which
        # only ever passes known column names, but defense in depth.
        allowed = {"duration_ms", "peak_rss_kb", "gpu_kernel_latency_ms",
                   "gpu_memory_used_mb", "gpu_utilization_pct"}
        if metric not in allowed:
            raise ValueError(f"unknown metric column: {metric}")
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {metric} FROM test_results "
                f"WHERE test_name = %s AND status = 'pass' "
                f"AND {metric} IS NOT NULL AND {metric} > 0 "
                f"ORDER BY id DESC LIMIT %s",
                (test_name, limit))
            rows = cur.fetchall()
        return [r[0] for r in reversed(rows)]

    def store_cluster(self, build_id: int, signature: str, component: str,
                       sample_message: str, count: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO failure_clusters(build_id, signature, component, "
                "sample_message, count) VALUES (%s, %s, %s, %s, %s)",
                (build_id, signature, component, sample_message, count))
        self.conn.commit()

    def get_clusters(self, build_id: int) -> list[dict]:
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM failure_clusters WHERE build_id = %s "
                "ORDER BY count DESC", (build_id,))
            return [dict(r) for r in cur.fetchall()]
