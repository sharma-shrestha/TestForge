"""Intelligent test selection.

Given:
    - a set of candidate tests (typically, tests relevant to a change)
    - historical failure data from storage
    - the dependency graph (already used to filter candidates upstream)
    - the set of components touched by the current change

Compute a score for each test and return the top-N (or all, scored).

Score = w1 * dependency_relevance
      + w2 * historical_failure_rate
      + w3 * recent_failure_frequency
      + w4 * performance_impact
      + w5 * execution_cost (penalty for slow tests - see below)

dependency_relevance is computed via real graph distance, not a flat 1.0/0.7/0.0
mapping:

  distance 0 (test is IN a changed component)            -> 1.0
  distance 1 (test depends on a changed component)      -> 0.7
  distance 2 (depends on something that depends on it)  -> 0.5
  distance 3                                            -> 0.3
  distance >= 4                                         -> 0.1
  no relation                                           -> 0.0

This means the score actually reflects how far the test is from the
change in the dependency graph, which the old code claimed but didn't do.

execution_cost is a penalty, not a bonus. A test that takes 30 seconds
should rank LOWER than a test that takes 0.1 seconds, all else equal,
because you can run 300 of the latter in the time it takes to run one
of the former. We compute this as:

  cost = min(1.0, median_duration_ms / 1000.0)   # 1.0 = 1 second or more

And subtract it from the score:

  final_score = score - w5 * cost

With default weights (w5 = 0.10), a 1-second test is penalized 0.10 points,
a 100ms test is penalized 0.01 points. This is small enough that a high-risk
slow test still ranks above a low-risk fast test, but among equally-risky
tests the faster ones run first.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from .config import SelectionWeights
from .dependency_graph import DependencyGraph
from .discovery import TestSpec


@dataclass
class TestScore:
    test: TestSpec
    score: float
    breakdown: dict[str, float]


def _graph_distance(graph: DependencyGraph, test_component: str,
                    changed_components: set[str]) -> int:
    """BFS shortest distance from test_component to any changed component.

    Returns 0 if test_component IS a changed component.
    Returns -1 if there's no path (test is unrelated to the change).
    """
    if test_component in changed_components:
        return 0
    if not graph.edges and not changed_components:
        return -1

    # BFS over the dependency graph. We treat "A depends on B" (graph.edges[A]
    # contains B) as: A is distance 1 from B. We want the shortest path from
    # test_component to ANY changed component.
    visited = {test_component}
    queue = deque([(test_component, 0)])
    while queue:
        node, dist = queue.popleft()
        if node in changed_components and dist > 0:
            return dist
        # Walk dependencies (A depends on B means edge A->B).
        for dep in graph.edges.get(node, set()):
            if dep not in visited:
                visited.add(dep)
                queue.append((dep, dist + 1))
        # Also walk dependents (reverse edges) - if a changed component
        # depends on us, we're also relevant.
        for dependent, deps in graph.edges.items():
            if node in deps and dependent not in visited:
                visited.add(dependent)
                queue.append((dependent, dist + 1))
    return -1


def _distance_to_relevance(distance: int) -> float:
    """Map graph distance to a relevance score in [0, 1]."""
    if distance < 0:
        return 0.0
    table = {0: 1.0, 1: 0.7, 2: 0.5, 3: 0.3}
    return table.get(distance, 0.1 if distance <= 10 else 0.0)


def score_tests(
    tests: list[TestSpec],
    history: "TestHistory",
    *,
    changed_components: set[str] | None = None,
    weights: SelectionWeights | None = None,
    graph: DependencyGraph | None = None,
) -> list[TestScore]:
    w = weights or SelectionWeights()
    changed_components = changed_components or set()

    out: list[TestScore] = []
    for t in tests:
        # 1. dependency relevance via real graph distance
        if graph and changed_components:
            dist = _graph_distance(graph, t.component, changed_components)
            dep_rel = _distance_to_relevance(dist)
        elif t.component in changed_components:
            dep_rel = 1.0
        elif any(d in changed_components for d in t.depends_on):
            dep_rel = 0.7
        else:
            dep_rel = 0.0

        # 2. historical failure rate (all executions)
        total = history.total_executions(t.name)
        failed = history.total_failures(t.name)
        hist_rate = (failed / total) if total > 0 else 0.0

        # 3. recent failure frequency (last 10 executions)
        recent = history.recent_results(t.name, limit=10)
        recent_fail_rate = (sum(1 for r in recent if r.status in ("fail", "timeout")) / len(recent)
                            if recent else 0.0)

        # 4. performance impact (1.0 if the test has ever recorded a perf
        # regression, 0.5 if it's a perf-tagged test, 0.0 otherwise)
        perf_impact = 1.0 if history.has_perf_regression(t.name) else (
            0.5 if "performance" in t.tags else 0.0
        )

        # 5. execution cost - penalize slow tests so faster tests rank higher
        # among equally-risky candidates.
        median_ms = history.median_duration_ms(t.name) if hasattr(history, "median_duration_ms") else 0.0
        cost = min(1.0, (median_ms / 1000.0) if median_ms > 0 else 0.0)

        score = (w.dependency_relevance      * dep_rel +
                 w.historical_failure_rate   * hist_rate +
                 w.recent_failure_frequency  * recent_fail_rate +
                 w.performance_impact        * perf_impact -
                 w.execution_cost            * cost)

        out.append(TestScore(
            test=t,
            score=score,
            breakdown={
                "dependency_relevance": dep_rel,
                "historical_failure_rate": hist_rate,
                "recent_failure_frequency": recent_fail_rate,
                "performance_impact": perf_impact,
                "execution_cost_penalty": cost,
                "graph_distance": _graph_distance(graph, t.component, changed_components) if graph else -1,
            },
        ))

    out.sort(key=lambda s: s.score, reverse=True)
    return out


def select_top_k(
    tests: list[TestSpec],
    history: "TestHistory",
    k: int,
    *,
    changed_components: set[str] | None = None,
    weights: SelectionWeights | None = None,
    graph: DependencyGraph | None = None,
) -> list[TestScore]:
    scored = score_tests(tests, history,
                         changed_components=changed_components,
                         weights=weights, graph=graph)
    return scored[:k]


# ---------------------------------------------------------------------------
# History protocol (so this module doesn't import storage directly - keeps
# it testable in isolation).
# ---------------------------------------------------------------------------

class TestHistory(Protocol):
    def total_executions(self, test_name: str) -> int: ...
    def total_failures(self, test_name: str) -> int: ...
    def recent_results(self, test_name: str, limit: int) -> list: ...
    def has_perf_regression(self, test_name: str) -> bool: ...
