"""Tests for the selection scorer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from testforge.config import SelectionWeights
from testforge.dependency_graph import DependencyGraph
from testforge.discovery import TestSpec
from testforge.selection import score_tests, select_top_k, _graph_distance, _distance_to_relevance
from testforge.storage import StoredResult


class _FakeStorage:
    def __init__(self, results_by_test):
        self.results = results_by_test

    def total_executions(self, name):
        return len(self.results.get(name, []))

    def total_failures(self, name):
        return sum(1 for r in self.results.get(name, [])
                   if r.status in ("fail", "timeout"))

    def recent_results(self, name, limit=10):
        return self.results.get(name, [])[:limit]

    def has_perf_regression(self, name):
        return any("PERF REGRESSION" in (r.failure_message or "")
                   for r in self.results.get(name, []))

    def median_duration_ms(self, name):
        results = self.results.get(name, [])
        durations = [r.duration_ms for r in results if r.duration_ms > 0]
        if not durations:
            return 0.0
        durations.sort()
        return durations[len(durations) // 2]

    def get_metric_history(self, name, metric, limit=20):
        return [getattr(r, metric, None) for r in self.results.get(name, [])
                if getattr(r, metric, None) and getattr(r, metric, None) > 0]


def _spec(name, component="", tags=None, depends_on=None):
    return TestSpec(name=name, suite="S", kind="cpp_engine", binary="b",
                    component=component, type="cpu", tags=tags or [],
                    depends_on=depends_on or [])


def _r(status, duration=1.0):
    return StoredResult(test_name="t", suite="", status=status, attempts=1,
                        duration_ms=duration)


# ---------------------------------------------------------------------------
# Graph-distance tests (the new functionality in v0.5)
# ---------------------------------------------------------------------------

def test_distance_to_relevance_table():
    assert _distance_to_relevance(0) == 1.0
    assert _distance_to_relevance(1) == 0.7
    assert _distance_to_relevance(2) == 0.5
    assert _distance_to_relevance(3) == 0.3
    assert _distance_to_relevance(5) == 0.1
    assert _distance_to_relevance(-1) == 0.0


def test_graph_distance_zero_for_changed_component():
    g = DependencyGraph()
    assert _graph_distance(g, "memory", {"memory"}) == 0


def test_graph_distance_one_for_direct_dependency():
    g = DependencyGraph()
    g.add_edge("tensor", "memory")    # tensor depends on memory
    # memory changed; tensor is distance 1
    assert _graph_distance(g, "tensor", {"memory"}) == 1


def test_graph_distance_two_for_transitive():
    g = DependencyGraph()
    g.add_edge("tensor", "memory")
    g.add_edge("inference", "tensor")
    # memory changed; inference is distance 2 (inference -> tensor -> memory)
    assert _graph_distance(g, "inference", {"memory"}) == 2


def test_graph_distance_negative_for_unrelated():
    g = DependencyGraph()
    g.add_edge("tensor", "memory")
    assert _graph_distance(g, "renderer", {"memory"}) == -1


def test_score_uses_graph_distance():
    g = DependencyGraph()
    g.add_edge("tensor", "memory")
    g.add_edge("inference", "tensor")
    storage = _FakeStorage({})
    tests = [
        _spec("A", "memory"),       # distance 0 -> 1.0
        _spec("B", "tensor"),       # distance 1 -> 0.7
        _spec("C", "inference"),    # distance 2 -> 0.5
        _spec("D", "renderer"),      # unrelated -> 0.0
    ]
    scored = score_tests(tests, storage, changed_components={"memory"}, graph=g)
    assert scored[0].test.name == "A"
    assert scored[1].test.name == "B"
    assert scored[2].test.name == "C"
    assert scored[3].test.name == "D"
    assert scored[0].breakdown["dependency_relevance"] == 1.0
    assert scored[1].breakdown["dependency_relevance"] == 0.7
    assert scored[2].breakdown["dependency_relevance"] == 0.5


# ---------------------------------------------------------------------------
# Existing tests (updated for the new fake storage methods)
# ---------------------------------------------------------------------------

def test_score_in_changed_component_is_highest():
    storage = _FakeStorage({})
    tests = [_spec("A", "memory"), _spec("B", "renderer")]
    scored = score_tests(tests, storage, changed_components={"memory"})
    assert scored[0].test.name == "A"
    assert scored[0].breakdown["dependency_relevance"] == 1.0


def test_score_with_high_failure_rate_ranks_higher():
    storage = _FakeStorage({
        "Failed": [_r("fail")] * 5 + [_r("pass")] * 5,
        "Stable": [_r("pass")] * 10,
    })
    tests = [_spec("Failed"), _spec("Stable")]
    scored = score_tests(tests, storage, changed_components=set())
    assert scored[0].test.name == "Failed"


def test_perf_impact_score_when_history_has_regression():
    storage = _FakeStorage({
        "T": [StoredResult(test_name="T", suite="", status="pass",
                            attempts=1, duration_ms=10,
                            failure_message="PERF REGRESSION")],
    })
    tests = [_spec("T")]
    scored = score_tests(tests, storage, changed_components=set())
    assert scored[0].breakdown["performance_impact"] == 1.0


def test_top_k_limits_results():
    storage = _FakeStorage({})
    tests = [_spec(f"T{i}", component=f"c{i}") for i in range(20)]
    scored = select_top_k(tests, storage, 5, changed_components={"c0"})
    assert len(scored) == 5
    assert scored[0].test.component == "c0"


def test_custom_weights_change_ranking():
    storage = _FakeStorage({
        "A": [_r("fail")] * 5 + [_r("pass")] * 5,
    })
    tests = [_spec("A"), _spec("B")]
    weights = SelectionWeights(
        dependency_relevance=0.0,
        historical_failure_rate=1.0,
        recent_failure_frequency=0.0,
        performance_impact=0.0,
        execution_cost=0.0,
    )
    scored = score_tests(tests, storage, changed_components=set(), weights=weights)
    assert scored[0].test.name == "A"


def test_execution_cost_penalizes_slow_tests():
    """A slow test should rank lower than a fast test with the same risk."""
    storage = _FakeStorage({
        "Fast": [_r("pass", duration=1.0)] * 10,     # 1ms
        "Slow": [_r("pass", duration=5000.0)] * 10,  # 5s
    })
    tests = [_spec("Fast"), _spec("Slow")]
    scored = score_tests(tests, storage, changed_components=set())
    assert scored[0].test.name == "Fast"
    assert scored[0].breakdown["execution_cost_penalty"] < scored[1].breakdown["execution_cost_penalty"]
