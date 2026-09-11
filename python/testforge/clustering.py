"""Failure clustering.

Groups failures by a stable signature so a developer looking at 50 failed
tests sees 3-5 clusters instead of 50 individual errors.

The signature is built by:
  1. Normalizing the failure_message (strip addresses, hex digits, paths
     to project root).
  2. Normalizing the stack_trace (collapse template arguments, strip line
     numbers, normalize file paths to project-relative).
  3. Hashing the normalized form.

This is rule-based. No ML involved. The LLM-based failure analyst is a
separate, optional module (assistant.py).
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class FailureCluster:
    signature: str
    component: str
    sample_message: str
    sample_file: str
    sample_line: int
    count: int
    test_names: list[str]


_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
_HEX_RE = re.compile(r"\b[0-9a-f]{16,}\b")
_NUM_RE = re.compile(r"\b\d+\b")
_TEMPLATE_RE = re.compile(r"<[^>]+>")
_PATH_RE = re.compile(r"/[\w./\-]+")


def normalize_message(msg: str) -> str:
    s = msg
    s = _ADDR_RE.sub("0xADDR", s)
    s = _HEX_RE.sub("0xHEX", s)
    # Leave small numbers - they're often meaningful (test IDs, line numbers
    # that survived path stripping, etc.).
    s = _TEMPLATE_RE.sub("<...>", s)
    s = _PATH_RE.sub("<path>", s)
    return s.strip()


def normalize_stack_trace(trace: str) -> str:
    # For stack traces we're more aggressive: also strip line numbers since
    # they shift between builds for unrelated reasons.
    s = trace
    s = _ADDR_RE.sub("0xADDR", s)
    s = _TEMPLATE_RE.sub("<...>", s)
    s = _PATH_RE.sub("<path>", s)
    s = _NUM_RE.sub("N", s)
    return s.strip()


def signature_for(message: str, stack_trace: str = "") -> str:
    norm = normalize_message(message)
    if stack_trace:
        norm += "\n" + normalize_stack_trace(stack_trace)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def cluster_failures(results: list) -> list[FailureCluster]:
    """Cluster a list of StoredResult-like objects (anything with
    .test_name, .status, .failure_message, .failure_file, .failure_line,
    .error_signature, .component)."""
    buckets: dict[str, list] = defaultdict(list)
    for r in results:
        if r.status not in ("fail", "timeout"):
            continue
        sig = r.error_signature or signature_for(r.failure_message or r.test_name)
        buckets[sig].append(r)

    clusters: list[FailureCluster] = []
    for sig, items in buckets.items():
        # Pick the first as the representative sample.
        first = items[0]
        clusters.append(FailureCluster(
            signature=sig,
            component=getattr(first, "component", "") or "",
            sample_message=first.failure_message,
            sample_file=first.failure_file,
            sample_line=first.failure_line,
            count=len(items),
            test_names=[i.test_name for i in items],
        ))
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters
