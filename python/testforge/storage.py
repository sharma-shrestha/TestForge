"""Storage layer.

Defines a StorageBackend interface and two implementations:
    - SQLiteBackend (default, zero-config)
    - PostgresBackend (optional, for multi-machine setups)

The schema is the same across both; only the SQL dialect differs slightly.
"""

from __future__ import annotations

import abc
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class StoredResult:
    test_name: str
    suite: str
    status: str
    attempts: int
    duration_ms: float
    failure_message: str = ""
    failure_file: str = ""
    failure_line: int = 0
    error_signature: str = ""
    peak_rss_kb: Optional[int] = None
    cpu_user_ms: Optional[float] = None
    cpu_sys_ms: Optional[float] = None
    gpu_utilization_pct: Optional[float] = None
    gpu_memory_used_mb: Optional[int] = None
    gpu_kernel_latency_ms: Optional[float] = None
    gpu_device_name: str = ""
    build_id: int = 0

    @classmethod
    def from_dict(cls, d: dict, build_id: int = 0) -> "StoredResult":
        return cls(
            test_name=d.get("test_name", ""),
            suite=d.get("suite", ""),
            status=d.get("status", ""),
            attempts=d.get("attempts", 0),
            duration_ms=d.get("duration_ms", 0.0),
            failure_message=d.get("failure_message", ""),
            failure_file=d.get("failure_file", ""),
            failure_line=d.get("failure_line", 0),
            error_signature=d.get("error_signature", ""),
            peak_rss_kb=d.get("peak_rss_kb"),
            cpu_user_ms=d.get("cpu_user_ms"),
            cpu_sys_ms=d.get("cpu_sys_ms"),
            gpu_utilization_pct=d.get("gpu_utilization_pct"),
            gpu_memory_used_mb=d.get("gpu_memory_used_mb"),
            gpu_kernel_latency_ms=d.get("gpu_kernel_latency_ms"),
            gpu_device_name=d.get("gpu_device_name", ""),
            build_id=build_id,
        )


SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS builds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
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
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id            INTEGER NOT NULL REFERENCES builds(id),
    test_name           TEXT NOT NULL,
    suite               TEXT,
    status              TEXT NOT NULL,
    attempts            INTEGER,
    duration_ms         REAL,
    failure_message     TEXT,
    failure_file        TEXT,
    failure_line        INTEGER,
    error_signature     TEXT,
    peak_rss_kb         INTEGER,
    cpu_user_ms         REAL,
    cpu_sys_ms          REAL,
    gpu_utilization_pct REAL,
    gpu_memory_used_mb  INTEGER,
    gpu_kernel_latency_ms REAL,
    gpu_device_name     TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_results_test ON test_results(test_name);
CREATE INDEX IF NOT EXISTS idx_results_build ON test_results(build_id);
CREATE INDEX IF NOT EXISTS idx_results_sig  ON test_results(error_signature);

CREATE TABLE IF NOT EXISTS perf_baselines (
    test_name           TEXT,
    metric              TEXT,
    baseline_value      REAL,
    sample_count        INTEGER,
    updated_at          TEXT,
    PRIMARY KEY (test_name, metric)
);

CREATE TABLE IF NOT EXISTS failure_clusters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id        INTEGER,
    signature       TEXT,
    component       TEXT,
    sample_message  TEXT,
    count           INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def create_build(self, *, git_sha: str = "", branch: str = "",
                     worker_count: int = 0, notes: str = "") -> int: ...

    @abc.abstractmethod
    def finish_build(self, build_id: int, *, status: str,
                     total: int, passed: int, failed: int,
                     flaky: int, skipped: int) -> None: ...

    @abc.abstractmethod
    def store_result(self, build_id: int, result: StoredResult) -> None: ...

    @abc.abstractmethod
    def get_results(self, build_id: int) -> list[StoredResult]: ...

    @abc.abstractmethod
    def recent_results(self, test_name: str, limit: int = 10) -> list[StoredResult]: ...

    @abc.abstractmethod
    def total_executions(self, test_name: str) -> int: ...

    @abc.abstractmethod
    def total_failures(self, test_name: str) -> int: ...

    @abc.abstractmethod
    def has_perf_regression(self, test_name: str) -> bool: ...

    @abc.abstractmethod
    def set_perf_baseline(self, test_name: str, metric: str,
                          value: float, sample_count: int = 1) -> None: ...

    @abc.abstractmethod
    def get_perf_baseline(self, test_name: str, metric: str) -> Optional[float]: ...

    @abc.abstractmethod
    def get_metric_history(self, test_name: str, metric: str,
                          limit: int = 20) -> list[float]: ...

    @abc.abstractmethod
    def store_cluster(self, build_id: int, signature: str, component: str,
                       sample_message: str, count: int) -> None: ...

    @abc.abstractmethod
    def get_clusters(self, build_id: int) -> list[dict]: ...


class SQLiteBackend(StorageBackend):
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQLITE)
        self._conn.commit()

    def create_build(self, *, git_sha: str = "", branch: str = "",
                     worker_count: int = 0, notes: str = "") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO builds(started_at, git_sha, branch, worker_count, notes) "
                "VALUES (datetime('now'), ?, ?, ?, ?)",
                (git_sha, branch, worker_count, notes),
            )
            self._conn.commit()
            return cur.lastrowid

    def finish_build(self, build_id: int, *, status: str,
                     total: int, passed: int, failed: int,
                     flaky: int, skipped: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE builds SET finished_at = datetime('now'), status = ?, "
                "total_tests = ?, passed = ?, failed = ?, flaky = ?, skipped = ? "
                "WHERE id = ?",
                (status, total, passed, failed, flaky, skipped, build_id),
            )
            self._conn.commit()

    def store_result(self, build_id: int, result: StoredResult) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO test_results (
                    build_id, test_name, suite, status, attempts, duration_ms,
                    failure_message, failure_file, failure_line, error_signature,
                    peak_rss_kb, cpu_user_ms, cpu_sys_ms,
                    gpu_utilization_pct, gpu_memory_used_mb,
                    gpu_kernel_latency_ms, gpu_device_name
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (build_id, result.test_name, result.suite, result.status,
                 result.attempts, result.duration_ms,
                 result.failure_message, result.failure_file, result.failure_line,
                 result.error_signature,
                 result.peak_rss_kb, result.cpu_user_ms, result.cpu_sys_ms,
                 result.gpu_utilization_pct, result.gpu_memory_used_mb,
                 result.gpu_kernel_latency_ms, result.gpu_device_name),
            )
            self._conn.commit()

    def get_results(self, build_id: int) -> list[StoredResult]:
        cur = self._conn.execute(
            "SELECT * FROM test_results WHERE build_id = ? ORDER BY id", (build_id,))
        rows = cur.fetchall()
        return [StoredResult(
            test_name=r["test_name"], suite=r["suite"], status=r["status"],
            attempts=r["attempts"], duration_ms=r["duration_ms"],
            failure_message=r["failure_message"] or "",
            failure_file=r["failure_file"] or "",
            failure_line=r["failure_line"] or 0,
            error_signature=r["error_signature"] or "",
            peak_rss_kb=r["peak_rss_kb"], cpu_user_ms=r["cpu_user_ms"],
            cpu_sys_ms=r["cpu_sys_ms"],
            gpu_utilization_pct=r["gpu_utilization_pct"],
            gpu_memory_used_mb=r["gpu_memory_used_mb"],
            gpu_kernel_latency_ms=r["gpu_kernel_latency_ms"],
            gpu_device_name=r["gpu_device_name"] or "",
            build_id=build_id,
        ) for r in rows]

    def recent_results(self, test_name: str, limit: int = 10) -> list[StoredResult]:
        cur = self._conn.execute(
            "SELECT * FROM test_results WHERE test_name = ? "
            "ORDER BY id DESC LIMIT ?", (test_name, limit))
        return [StoredResult(**dict(r)) for r in cur.fetchall()]

    def total_executions(self, test_name: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM test_results WHERE test_name = ?",
            (test_name,))
        return cur.fetchone()[0]

    def total_failures(self, test_name: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM test_results WHERE test_name = ? AND status IN ('fail','timeout')",
            (test_name,))
        return cur.fetchone()[0]

    def has_perf_regression(self, test_name: str) -> bool:
        # Stored as a tag in failure_message when perf regression detected.
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM test_results WHERE test_name = ? "
            "AND failure_message LIKE '%PERF REGRESSION%'", (test_name,))
        return cur.fetchone()[0] > 0

    def set_perf_baseline(self, test_name: str, metric: str,
                           value: float, sample_count: int = 1) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO perf_baselines(test_name, metric, baseline_value, "
                "sample_count, updated_at) VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(test_name, metric) DO UPDATE SET "
                "baseline_value = excluded.baseline_value, "
                "sample_count = excluded.sample_count, "
                "updated_at = datetime('now')",
                (test_name, metric, value, sample_count))
            self._conn.commit()

    def get_perf_baseline(self, test_name: str, metric: str) -> Optional[float]:
        cur = self._conn.execute(
            "SELECT baseline_value FROM perf_baselines WHERE test_name = ? AND metric = ?",
            (test_name, metric))
        row = cur.fetchone()
        return row[0] if row else None

    def get_metric_history(self, test_name: str, metric: str,
                          limit: int = 20) -> list[float]:
        """Returns the last `limit` values of `metric` for `test_name`,
        oldest first. Only includes values from passing runs (a failed
        run's metric is likely garbage - e.g. a timeout's duration_ms
        is the timeout value, not the real execution time).
        """
        cur = self._conn.execute(
            f"SELECT {metric} FROM test_results "
            f"WHERE test_name = ? AND status = 'pass' AND {metric} IS NOT NULL AND {metric} > 0 "
            f"ORDER BY id DESC LIMIT ?",
            (test_name, limit))
        rows = cur.fetchall()
        # Return oldest-first (we queried DESC, so reverse).
        return [r[0] for r in reversed(rows)]

    def store_cluster(self, build_id: int, signature: str, component: str,
                       sample_message: str, count: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO failure_clusters(build_id, signature, component, "
                "sample_message, count) VALUES (?, ?, ?, ?, ?)",
                (build_id, signature, component, sample_message, count))
            self._conn.commit()

    def get_clusters(self, build_id: int) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM failure_clusters WHERE build_id = ? ORDER BY count DESC",
            (build_id,))
        return [dict(r) for r in cur.fetchall()]


def open_storage(config) -> StorageBackend:
    backend = config.storage.get("backend", "sqlite")
    if backend == "sqlite":
        path = config.project_root / config.storage.get("sqlite_path", ".testforge/testforge.db")
        return SQLiteBackend(path)
    elif backend == "postgres":
        try:
            from .postgres_backend import PostgresBackend
        except ImportError as e:
            raise RuntimeError(
                "PostgreSQL backend requires psycopg2-binary. "
                "Install with: pip install testforge[postgres]"
            ) from e
        return PostgresBackend(config.storage["dsn"])
    raise ValueError(f"unknown storage backend: {backend}")
