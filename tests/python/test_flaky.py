"""Tests for flaky test detection."""

import sys
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from testforge.flaky import compute_flakiness, scan_flaky
from testforge.storage import StoredResult


class _FakeStorage:
    """In-memory StorageBackend stub for testing without SQLite."""
    def __init__(self, results_by_test: dict[str, list[StoredResult]]):
        self.results = results_by_test

    def recent_results(self, test_name, limit=10):
        return self.results.get(test_name, [])[:limit]

    def total_executions(self, test_name):
        return len(self.results.get(test_name, []))

    def total_failures(self, test_name):
        return sum(1 for r in self.results.get(test_name, [])
                   if r.status in ("fail", "timeout"))

    def has_perf_regression(self, test_name):
        return any("PERF REGRESSION" in (r.failure_message or "")
                   for r in self.results.get(test_name, []))

    # The rest of the StorageBackend interface isn't exercised here.
    def create_build(self, **kw): return 1
    def finish_build(self, *a, **kw): pass
    def store_result(self, *a, **kw): pass
    def get_results(self, *a, **kw): return []
    def set_perf_baseline(self, *a, **kw): pass
    def get_perf_baseline(self, *a, **kw): return None
    def get_metric_history(self, *a, **kw): return []
    def store_cluster(self, *a, **kw): pass
    def get_clusters(self, *a, **kw): return []


def _r(status):
    return StoredResult(test_name="t", suite="", status=status, attempts=1, duration_ms=1.0)


def test_pure_pass_not_flaky():
    storage = _FakeStorage({"t": [_r("pass")] * 10})
    report = compute_flakiness("t", storage, threshold=0.15)
    assert report.flakiness == 0.0
    assert not report.quarantined


def test_pure_fail_not_flaky():
    storage = _FakeStorage({"t": [_r("fail")] * 10})
    report = compute_flakiness("t", storage, threshold=0.15)
    assert report.flakiness == 0.0


def test_mixed_results_are_flaky():
    storage = _FakeStorage({"t": [_r("pass"), _r("fail")] * 5})
    report = compute_flakiness("t", storage, threshold=0.15)
    assert 0.4 < report.flakiness < 0.6
    assert report.quarantined


def test_scan_orders_by_flakiness_desc():
    storage = _FakeStorage({
        "high": [_r("pass"), _r("fail")] * 5,
        "low":  [_r("fail")] + [_r("pass")] * 19,
    })
    reports = scan_flaky(["low", "high"], storage, threshold=0.15)
    assert reports[0].test_name == "high"
    assert reports[0].flakiness > reports[1].flakiness


def test_no_history_returns_zero():
    storage = _FakeStorage({})
    report = compute_flakiness("unknown", storage)
    assert report.flakiness == 0.0
    assert report.sample_size == 0
