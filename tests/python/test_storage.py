"""Tests for the storage layer.

Uses a real in-memory SQLite database (sqlite3 supports ":memory:") so we
exercise the actual schema and SQL, just without touching the filesystem.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from testforge.storage import SQLiteBackend, StoredResult


def _make_backend(tmp_path):
    return SQLiteBackend(str(tmp_path / "test.db"))


def _result(name, status="pass", duration=10.0):
    return StoredResult(
        test_name=name, suite="S", status=status, attempts=1,
        duration_ms=duration, failure_message="" if status == "pass" else "boom",
    )


def test_create_and_finish_build(tmp_path):
    b = _make_backend(tmp_path)
    bid = b.create_build(git_sha="abc123", branch="main", worker_count=4)
    assert bid > 0
    b.finish_build(bid, status="passed", total=10, passed=10, failed=0, flaky=0, skipped=0)


def test_store_and_retrieve_result(tmp_path):
    b = _make_backend(tmp_path)
    bid = b.create_build()
    b.store_result(bid, _result("Test1", "pass", 12.3))
    results = b.get_results(bid)
    assert len(results) == 1
    assert results[0].test_name == "Test1"
    assert results[0].status == "pass"
    assert abs(results[0].duration_ms - 12.3) < 0.01


def test_total_executions_counts_all_runs(tmp_path):
    b = _make_backend(tmp_path)
    bid = b.create_build()
    b.store_result(bid, _result("Test1", "pass"))
    b.store_result(bid, _result("Test1", "fail"))
    b.store_result(bid, _result("Test1", "pass"))
    assert b.total_executions("Test1") == 3
    assert b.total_failures("Test1") == 1


def test_perf_baseline_round_trip(tmp_path):
    b = _make_backend(tmp_path)
    b.set_perf_baseline("Test1", "duration_ms", 12.5, sample_count=10)
    assert abs(b.get_perf_baseline("Test1", "duration_ms") - 12.5) < 0.001


def test_perf_baseline_overwrite(tmp_path):
    b = _make_backend(tmp_path)
    b.set_perf_baseline("T", "duration_ms", 10.0)
    b.set_perf_baseline("T", "duration_ms", 15.0)
    assert abs(b.get_perf_baseline("T", "duration_ms") - 15.0) < 0.001


def test_store_and_get_clusters(tmp_path):
    b = _make_backend(tmp_path)
    bid = b.create_build()
    b.store_cluster(bid, "sig1", "memory", "boom", 5)
    b.store_cluster(bid, "sig2", "tensor", "crunch", 2)
    clusters = b.get_clusters(bid)
    assert len(clusters) == 2
    # Sorted by count desc.
    assert clusters[0]["count"] == 5
    assert clusters[0]["signature"] == "sig1"


def test_has_perf_regression(tmp_path):
    b = _make_backend(tmp_path)
    bid = b.create_build()
    b.store_result(bid, StoredResult(
        test_name="T", suite="", status="pass", attempts=1, duration_ms=10,
        failure_message="PERF REGRESSION detected",
    ))
    assert b.has_perf_regression("T")
