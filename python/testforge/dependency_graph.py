"""Dependency graph.

Models component-to-component dependencies (the "memory allocator depends on
tensor engine depends on inference engine" kind of relationship). When a
file changes, we walk the graph upward to find all transitive dependents,
and any test that touches one of those dependents is considered relevant.

This is intentionally a simple directed graph with reachability - no fancy
topological sort, no SCC, because we don't need a build order here, we just
need "what's downstream of X".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from .discovery import TestSpec


@dataclass
class DependencyGraph:
    # edges: A -> B means "A depends on B" (B is upstream of A).
    # So when B changes, A's tests should run.
    edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # component -> list of source files (used to map a changed file to a component)
    files_by_component: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_edge(self, dependent: str, dependency: str) -> None:
        self.edges[dependent].add(dependency)

    def add_file(self, component: str, path: str) -> None:
        self.files_by_component[component].append(path)

    def component_for_file(self, path: str) -> str | None:
        for comp, files in self.files_by_component.items():
            for f in files:
                # Match on suffix so relative paths work either way.
                if path.endswith(f) or f.endswith(path):
                    return comp
        return None

    def dependents_of(self, component: str) -> set[str]:
        """All components that transitively depend on `component`."""
        seen: set[str] = set()
        stack = [component]
        # invert edges: dependency -> set of dependents
        inverse: dict[str, set[str]] = defaultdict(set)
        for dep, deps in self.edges.items():
            for d in deps:
                inverse[d].add(dep)
        while stack:
            cur = stack.pop()
            for nxt in inverse.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def relevant_components(self, changed_files: Iterable[str]) -> set[str]:
        """Components affected by a change in any of `changed_files`."""
        relevant: set[str] = set()
        for path in changed_files:
            comp = self.component_for_file(path)
            if comp is None:
                continue
            relevant.add(comp)
            relevant.update(self.dependents_of(comp))
        return relevant

    def relevant_tests(self, tests: list[TestSpec], changed_files: Iterable[str]) -> list[TestSpec]:
        rel = self.relevant_components(changed_files)
        out = [t for t in tests
               if t.component in rel
               or any(d in rel for d in t.depends_on)]
        return out

    @classmethod
    def from_manifest(cls, path: Path) -> "DependencyGraph":
        g = cls()
        if not path.exists():
            return g
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for comp in data.get("components", []):
            name = comp["name"]
            for f in comp.get("files", []):
                g.add_file(name, f)
            for dep in comp.get("depends_on", []):
                g.add_edge(name, dep)
        return g
