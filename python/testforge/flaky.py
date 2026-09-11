"""Flaky test detection.

A test is "flaky" if its pass/fail outcome varies across executions on the
same code. We compute a flakiness score as:

    flakiness = (number of executions with mixed outcomes) /
                (total number of executions)

where an "execution" is one logical test run (we collapse retries into a
single execution since retries-on-pass is what makes a test flaky in the
first place).

Tests above a configurable threshold (default 0.15) are quarantined: they
keep running but their failures don't fail the build, and they're flagged
in the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from .storage import StoredResult, StorageBackend


@dataclass
class FlakyReport:
    test_name: str
    flakiness: float
    sample_size: int
    quarantined: bool


def compute_flakiness(
    test_name: str,
    storage: StorageBackend,
    threshold: float = 0.15,
    sample_limit: int = 100,
) -> FlakyReport:
    # recent_results returns most-recent-first; we want chronological order.
    recent = list(reversed(storage.recent_results(test_name, limit=sample_limit)))
    if not recent:
        return FlakyReport(test_name, flakiness=0.0, sample_size=0,
                            quarantined=False)

    # Group by "outcome class" - pass-ish vs fail-ish.
    pass_count = sum(1 for r in recent if r.status in ("pass", "flaky"))
    fail_count = sum(1 for r in recent if r.status in ("fail", "timeout"))
    total = len(recent)

    if pass_count == 0 or fail_count == 0:
        # Pure pass or pure fail - not flaky.
        return FlakyReport(test_name, flakiness=0.0, sample_size=total,
                            quarantined=False)

    # Fraction of executions where the outcome differs from the majority.
    minority = min(pass_count, fail_count)
    flakiness = minority / total
    return FlakyReport(
        test_name=test_name,
        flakiness=flakiness,
        sample_size=total,
        quarantined=flakiness > threshold,
    )


def scan_flaky(
    test_names: list[str],
    storage: StorageBackend,
    threshold: float = 0.15,
) -> list[FlakyReport]:
    out = []
    for name in test_names:
        out.append(compute_flakiness(name, storage, threshold))
    out.sort(key=lambda f: f.flakiness, reverse=True)
    return out
