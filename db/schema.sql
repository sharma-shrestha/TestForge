-- TestForge schema (SQLite flavor)
-- This file is for reference. The actual schema is created in code by
-- SQLiteBackend on first connection. Keeping this file in sync is a
-- manual process - see db/schema.md for the canonical reference.

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

CREATE INDEX IF NOT EXISTS idx_results_test  ON test_results(test_name);
CREATE INDEX IF NOT EXISTS idx_results_build ON test_results(build_id);
CREATE INDEX IF NOT EXISTS idx_results_sig   ON test_results(error_signature);

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
