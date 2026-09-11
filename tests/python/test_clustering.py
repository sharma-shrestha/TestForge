"""Tests for clustering.

The clustering module is pure logic - no I/O, no globals - so it's the
easiest place to start with tests.
"""

import sys
from pathlib import Path

# Make the testforge package importable when running pytest from the
# project root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from testforge.clustering import (
    FailureCluster,
    cluster_failures,
    normalize_message,
    signature_for,
)


class _FakeResult:
    """Minimal duck-typed object that quacks like StoredResult."""
    def __init__(self, name, status, message, signature="", component=""):
        self.test_name = name
        self.status = status
        self.failure_message = message
        self.failure_file = ""
        self.failure_line = 0
        self.error_signature = signature
        self.component = component


def test_signature_is_stable_across_addresses():
    a = signature_for("segfault at 0xdeadbeef in libfoo.so")
    b = signature_for("segfault at 0xfeedface in libfoo.so")
    assert a == b, "signatures should be identical after address normalization"


def test_signature_differs_for_different_messages():
    a = signature_for("null pointer at line 42")
    b = signature_for("out of memory at line 17")
    assert a != b


def test_normalize_strips_paths():
    s = normalize_message("failed in /home/user/proj/src/foo.cpp:42")
    assert "/home/user/proj" not in s
    assert "<path>" in s


def test_cluster_groups_by_signature():
    results = [
        _FakeResult("Test1", "fail", "segfault at 0x123"),
        _FakeResult("Test2", "fail", "segfault at 0x456"),
        _FakeResult("Test3", "fail", "out of memory"),
        _FakeResult("Test4", "pass", "ignored"),
    ]
    clusters = cluster_failures(results)
    assert len(clusters) == 2
    # The two segfaults cluster together.
    segfault_cluster = next(c for c in clusters if "segfault" in c.sample_message)
    assert segfault_cluster.count == 2
    assert set(segfault_cluster.test_names) == {"Test1", "Test2"}


def test_cluster_uses_error_signature_when_present():
    """If the result already has an error_signature, we trust it.

    This matters because the worker computes signatures at execution time
    (with access to the actual stack trace), and we want the post-hoc
    clustering to match.
    """
    results = [
        _FakeResult("A", "fail", "msg1", signature="sig1"),
        _FakeResult("B", "fail", "msg2", signature="sig1"),  # same sig
        _FakeResult("C", "fail", "msg3", signature="sig2"),
    ]
    clusters = cluster_failures(results)
    assert len(clusters) == 2
    by_count = sorted(clusters, key=lambda c: -c.count)
    assert by_count[0].count == 2
    assert by_count[0].signature == "sig1"


def test_empty_input_returns_empty_list():
    assert cluster_failures([]) == []
