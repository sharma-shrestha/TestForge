"""Tests for the dependency graph."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from testforge.dependency_graph import DependencyGraph
from testforge.discovery import TestSpec


def _spec(name, component):
    return TestSpec(name=name, suite="S", kind="cpp_engine", binary="b",
                    component=component, type="cpu")


def test_dependents_of_walks_transitively():
    g = DependencyGraph()
    g.add_edge("inference_engine", "tensor_engine")
    g.add_edge("tensor_engine", "memory_allocator")
    # memory_allocator changed → should reach both tensor_engine and inference_engine
    deps = g.dependents_of("memory_allocator")
    assert deps == {"tensor_engine", "inference_engine"}


def test_relevant_components_includes_changed_file():
    g = DependencyGraph()
    g.add_file("memory_allocator", "src/memory/allocator.cpp")
    g.add_edge("tensor_engine", "memory_allocator")
    rel = g.relevant_components(["src/memory/allocator.cpp"])
    assert "memory_allocator" in rel
    assert "tensor_engine" in rel


def test_relevant_tests_filters_by_component():
    g = DependencyGraph()
    g.add_file("memory_allocator", "src/mem.cpp")
    g.add_edge("tensor_engine", "memory_allocator")

    tests = [
        _spec("MemTest", "memory_allocator"),
        _spec("TensorTest", "tensor_engine"),
        _spec("UnrelatedTest", "renderer"),
    ]
    relevant = g.relevant_tests(tests, ["src/mem.cpp"])
    names = [t.name for t in relevant]
    assert "MemTest" in names
    assert "TensorTest" in names
    assert "UnrelatedTest" not in names


def test_relevant_tests_uses_depends_on_metadata():
    g = DependencyGraph()
    g.add_file("memory_allocator", "src/mem.cpp")

    tests = [
        _spec("A", "tensor_engine"),
    ]
    tests[0].depends_on = ["memory_allocator"]
    relevant = g.relevant_tests(tests, ["src/mem.cpp"])
    assert relevant == tests


def test_unknown_file_yields_no_components():
    g = DependencyGraph()
    assert g.relevant_components(["/nonexistent.cpp"]) == set()
