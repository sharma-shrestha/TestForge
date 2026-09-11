"""Regression detection.

Three flavors of regression:

  - functional   : test status went from pass to fail
  - performance  : latency grew beyond a threshold vs baseline
  - resource     : memory usage grew beyond a threshold vs baseline

Baseline algorithm (v0.5, replaces the old exponential smoothing):

The old approach was `new_baseline = old * 0.95 + current * 0.05`. This
absorbs genuine regressions over time: a persistent 8% slowdown becomes
the new normal after enough runs, and the next 8% slowdown on top of
that also gets absorbed.

The new approach uses robust statistics on the recent history:

  1. Fetch the last N (default 20) passing runs of this metric.
  2. Compute the median (robust to outliers - a single slow run doesn't
     move it).
  3. Compute MAD (median absolute deviation) as the spread.
  4. Flag a regression if BOTH:
       current > median * (1 + threshold/100)   # percentage check
       current > median + 3 * MAD                # statistical check

The dual check means: "the current run is both meaningfully slower than
the typical run AND statistically unusual." A test that's noisy (high
MAD) won't trigger on small percentage changes; a test that's stable
(low MAD) will trigger on exactly the threshold.

When a regression is NOT flagged, we don't update a smoothed baseline -
the next run just fetches the history again. This means the baseline
tracks the actual distribution of recent runs, not a drifted average.

For the first few runs (< 5 samples), we don't have enough data to be
statistical - we fall back to a simple percentage check against the
median, and we store the value in perf_baselines as before so it shows
up in the dashboard.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .config import RegressionThresholds
from .storage import StoredResult, StorageBackend


@dataclass
class Regression:
    test_name: str
    kind: str           # "functional" | "performance" | "resource"
    metric: str         # e.g. "duration_ms", "peak_rss_kb", "gpu_kernel_latency_ms"
    baseline: float
    current: float
    delta_pct: float
    threshold_pct: float
    message: str


def detect_regressions(
    results: list[StoredResult],
    storage: StorageBackend,
    thresholds: RegressionThresholds,
) -> list[Regression]:
    out: list[Regression] = []
    for r in results:
        # Functional regression: status is fail or timeout.
        if r.status in ("fail", "timeout"):
            out.append(Regression(
                test_name=r.test_name,
                kind="functional",
                metric="status",
                baseline=0, current=1, delta_pct=100, threshold_pct=0,
                message=f"{r.test_name} failed: {r.failure_message}",
            ))
            # A failed test may still have a perf baseline to check, but we
            # usually don't care about perf on a functionally broken test.
            continue

        # Performance regression (CPU): duration_ms vs baseline.
        out.extend(_check_metric(r, storage, thresholds.perf_pct,
                                  "duration_ms", "performance"))
        # Performance regression (GPU): gpu_kernel_latency_ms vs baseline.
        if r.gpu_kernel_latency_ms is not None and r.gpu_kernel_latency_ms > 0:
            out.extend(_check_metric(r, storage, thresholds.gpu_latency_pct,
                                      "gpu_kernel_latency_ms", "performance"))
        # Resource regression: peak_rss_kb.
        if r.peak_rss_kb is not None and r.peak_rss_kb > 0:
            out.extend(_check_metric(r, storage, thresholds.memory_pct,
                                      "peak_rss_kb", "resource"))
        # Resource regression: GPU memory.
        if r.gpu_memory_used_mb is not None and r.gpu_memory_used_mb > 0:
            out.extend(_check_metric(r, storage, thresholds.gpu_memory_pct,
                                      "gpu_memory_used_mb", "resource"))
    return out


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.median(values)


def _mad(values: list[float], med: float) -> float:
    """Median Absolute Deviation - robust measure of spread."""
    if not values:
        return 0.0
    deviations = [abs(v - med) for v in values]
    return statistics.median(deviations)


def _check_metric(
    r: StoredResult,
    storage: StorageBackend,
    threshold_pct: float,
    metric: str,
    kind: str,
) -> list[Regression]:
    current = getattr(r, metric, None)
    if current is None or current <= 0:
        return []

    # Fetch the history of this metric for this test (passing runs only).
    history = storage.get_metric_history(r.test_name, metric, limit=20)

    if not history:
        # First ever run - record it as the baseline, don't flag.
        storage.set_perf_baseline(r.test_name, metric, float(current),
                                   sample_count=1)
        return []

    median = _median(history)

    if median <= 0:
        return []

    # Always update the stored baseline to the current median so the
    # dashboard shows a meaningful number. This is NOT exponential
    # smoothing - it's the actual median of recent runs, which is robust
    # to a single outlier.
    storage.set_perf_baseline(r.test_name, metric, median,
                               sample_count=len(history))

    delta_pct = ((current - median) / median) * 100.0

    # Percentage check: is current > median * (1 + threshold/100)?
    exceeds_pct = delta_pct > threshold_pct

    # Statistical check: is current unusual given the spread?
    # We use 3*MAD as the threshold (roughly equivalent to 3-sigma for
    # normal distributions, but robust to outliers).
    spread = _mad(history, median)
    statistical_cutoff = median + 3 * spread
    exceeds_statistical = current > statistical_cutoff

    # For the first few runs (< 5 samples), MAD is unreliable, so we
    # only use the percentage check.
    if len(history) < 5:
        exceeds_statistical = True

    if exceeds_pct and exceeds_statistical:
        return [Regression(
            test_name=r.test_name,
            kind=kind,
            metric=metric,
            baseline=median,
            current=current,
            delta_pct=delta_pct,
            threshold_pct=threshold_pct,
            message=(f"PERF REGRESSION {kind} on {r.test_name} for "
                     f"{metric}: baseline(median)={median:.3f}, "
                     f"current={current:.3f}, "
                     f"delta=+{delta_pct:.2f}% (threshold={threshold_pct}%, "
                     f"MAD={spread:.3f}, samples={len(history)})"),
        )]

    return []
