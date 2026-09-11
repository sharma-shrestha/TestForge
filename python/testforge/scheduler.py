"""Worker pool + scheduler.

The orchestrator owns a pool of N worker processes. Each worker is a
subprocess that runs a test binary on a subset of tests. Results are
collected from each worker's stdout (JSON) and parsed.

Key architectural point (fixed in v0.5):

  There is no separate "testforge_worker" binary. Each test binary
  (example_cpp_tests, example_gpu_tests, your own test binaries) IS a
  worker - it links libtestforge_core, registers its tests at static-init
  time via the TEST() macro, and provides a main() that delegates to
  testforge_main(). The orchestrator invokes the test binary directly
  with --filter name1,name2,... and parses the JSON report from stdout.

This means the test binary contains BOTH the test code AND the engine
that runs it. No more "worker with empty registry" problem.

Why subprocess-based and not thread-based?

  1. Crash isolation: a SEGFAULT in one worker doesn't lose results
     from other workers.
  2. Real timeout: subprocess.run(timeout=...) kills the child cleanly.
     In-process threads can't be cancelled in C++.
  3. Sharding: tests from different binaries (cpu_tests, gpu_tests) run
     in separate processes, so their registries don't conflict.

Per-test timeout is enforced by the orchestrator: each test runs in its
own subprocess invocation (binary + --filter name). This is slightly
slower than batching (one subprocess per shard) but gives correct per-
test timeout semantics - a hung test doesn't take down the whole shard.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .discovery import TestSpec
from .storage import StoredResult


@dataclass
class WorkerJob:
    worker_id: int
    tests: list[TestSpec]
    binary: str           # path to the test binary
    kind: str             # "cpp_engine" | "pytest" | "binary"


@dataclass
class WorkerResult:
    worker_id: int
    results: list[dict]
    elapsed_s: float
    ok: bool
    error: str = ""


# Parses structured metric lines from stderr. The worker emits lines like:
#   test_name=GPU.MatrixMultiply
#   gpu_kernel_latency_ms=14.2
# We associate metrics with the most recently emitted test_name.
_TEST_NAME_RE = re.compile(r"^test_name=(.+)$", re.MULTILINE)
_GPU_LATENCY_RE = re.compile(r"gpu_kernel_latency_ms=([\d.]+)")


def run_tests_parallel(
    specs: list[TestSpec],
    config: Config,
    build_id: int,
    storage,
) -> list[StoredResult]:
    """Run `specs` in parallel, store results, return them.

    Tests are grouped by their binary field - each binary is invoked
    with --filter name1,name2,... to run a subset of its tests. Multiple
    binaries run in parallel (up to config.default_workers concurrent).

    Within a single binary, tests run sequentially (the C++ engine is
    single-threaded by design - parallelism comes from multiple worker
    processes, not threads within one worker).
    """
    if not specs:
        return []

    n_workers = config.default_workers or os.cpu_count() or 4

    # Group specs by binary so we invoke each binary with the right --filter.
    by_binary: dict[str, list[TestSpec]] = {}
    for s in specs:
        by_binary.setdefault(s.binary, []).append(s)

    # Shard each binary's tests across workers.
    jobs: list[WorkerJob] = []
    for binary, group in by_binary.items():
        shards = max(1, min(n_workers, len(group)))
        for i in range(shards):
            shard = group[i::shards]
            if not shard:
                continue
            jobs.append(WorkerJob(
                worker_id=len(jobs),
                tests=shard,
                binary=binary,
                kind=group[0].kind,
            ))

    all_results: list[StoredResult] = []
    all_results_lock = threading.Lock()

    def _do(job: WorkerJob) -> WorkerResult:
        t0 = time.monotonic()
        try:
            if job.kind == "cpp_engine":
                results = _run_cpp_engine_job(job, config)
            elif job.kind == "pytest":
                results = _run_pytest_job(job, config)
            elif job.kind == "binary":
                results = _run_binary_job(job, config)
            else:
                results = []
        except Exception as e:
            return WorkerResult(worker_id=job.worker_id, results=[],
                                  elapsed_s=time.monotonic() - t0,
                                  ok=False, error=str(e))

        with all_results_lock:
            for r in results:
                sr = StoredResult.from_dict(r, build_id)
                storage.store_result(build_id, sr)
                all_results.append(sr)

        return WorkerResult(worker_id=job.worker_id, results=results,
                            elapsed_s=time.monotonic() - t0, ok=True)

    with ThreadPoolExecutor(max_workers=min(n_workers, len(jobs))) as ex:
        futures = [ex.submit(_do, job) for job in jobs]
        for fut in as_completed(futures):
            fut.result()  # exceptions are captured in WorkerResult

    return all_results


def _resolve_binary(binary: str, config: Config) -> str:
    """Resolve a binary path relative to the project root if needed."""
    if Path(binary).is_absolute() and Path(binary).exists():
        return binary
    candidate = config.project_root / binary
    if candidate.exists():
        return str(candidate)
    # Last resort: check if it's on PATH.
    from shutil import which
    found = which(binary)
    if found:
        return found
    raise FileNotFoundError(
        f"test binary not found: {binary} "
        f"(looked in {config.project_root} and on PATH; "
        f"run `cmake --build build` or `python scripts/build.py` first)"
    )


def _run_cpp_engine_job(job: WorkerJob, config: Config) -> list[dict]:
    """Run a shard of cpp_engine tests.

    Each test is run in its own subprocess invocation so we get correct
    per-test timeout semantics. A hung test is killed without affecting
    other tests in the shard.
    """
    binary = _resolve_binary(job.binary, config)
    results: list[dict] = []

    for spec in job.tests:
        timeout_s = max(spec.timeout_ms / 1000.0, 1.0)
        try:
            proc = subprocess.run(
                [binary, "--filter", spec.name],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            # The test hung. Mark it as timeout and move on - the subprocess
            # was killed by subprocess.run, so no leaked process.
            results.append({
                "test_name": spec.name,
                "suite": spec.suite,
                "status": "timeout",
                "attempts": 1,
                "duration_ms": timeout_s * 1000,
                "failure_message": f"timed out after {timeout_s:.1f}s",
                "failure_file": "",
                "failure_line": 0,
                "error_signature": f"timeout:{spec.name}",
                "peak_rss_kb": None,
                "cpu_user_ms": None,
                "cpu_sys_ms": None,
                "gpu_kernel_latency_ms": None,
                "gpu_utilization_pct": None,
                "gpu_memory_used_mb": None,
                "gpu_device_name": "",
            })
            continue

        # Parse the JSON line from stdout.
        json_out = proc.stdout.strip().splitlines()
        if not json_out or not json_out[-1].startswith("{"):
            results.append({
                "test_name": spec.name,
                "suite": spec.suite,
                "status": "fail",
                "attempts": 1,
                "duration_ms": 0.0,
                "failure_message": f"worker produced no JSON output. stderr: {proc.stderr[-500:]}",
                "error_signature": "no-output",
            })
            continue

        report = json.loads(json_out[-1])
        report_results = report.get("results", [])

        # Attach GPU metrics parsed from stderr, matched by test_name
        # (not by index - the old index-based approach was fragile when
        # some tests emitted metrics and others didn't).
        gpu_metrics = _parse_gpu_metrics_by_test(proc.stderr)
        for r in report_results:
            name = r.get("test_name", "")
            if name in gpu_metrics:
                r.update(gpu_metrics[name])

        results.extend(report_results)

    return results


def _parse_gpu_metrics_by_test(stderr: str) -> dict[str, dict]:
    """Parse structured metric lines from stderr, keyed by test_name.

    The worker emits lines like:
        test_name=GPU.MatrixMultiply
        gpu_kernel_latency_ms=14.2
        test_name=GPU.VectorAdd
        gpu_kernel_latency_ms=0.5

    We associate each metric line with the most recently emitted test_name.
    """
    metrics: dict[str, dict] = {}
    current_test = ""
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("test_name="):
            current_test = line[len("test_name="):]
            metrics.setdefault(current_test, {})
        elif line.startswith("gpu_kernel_latency_ms="):
            try:
                v = float(line[len("gpu_kernel_latency_ms="):])
                if current_test:
                    metrics[current_test]["gpu_kernel_latency_ms"] = v
            except ValueError:
                pass
    return metrics


def _run_pytest_job(job: WorkerJob, config: Config) -> list[dict]:
    cmd = ["pytest", "-q", "--tb=short"]
    for spec in job.tests:
        cmd.append(spec.binary + "::" + spec.name.split(".", 1)[1])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    results = []
    for spec in job.tests:
        func = spec.name.split(".", 1)[1]
        passed = (f"{spec.binary}::{func} PASSED" in proc.stdout or
                  f"{func} PASSED" in proc.stdout)
        results.append({
            "test_name": spec.name,
            "suite": spec.suite,
            "status": "pass" if passed else "fail",
            "attempts": 1,
            "duration_ms": 0.0,
            "failure_message": "" if passed else proc.stdout[-500:],
        })
    return results


def _run_binary_job(job: WorkerJob, config: Config) -> list[dict]:
    results = []
    for spec in job.tests:
        proc = subprocess.run(
            [spec.binary], capture_output=True, text=True,
            timeout=spec.timeout_ms / 1000)
        results.append({
            "test_name": spec.name,
            "suite": spec.suite,
            "status": "pass" if proc.returncode == 0 else "fail",
            "attempts": 1,
            "duration_ms": 0.0,
            "failure_message": proc.stderr[-500:] if proc.returncode != 0 else "",
        })
    return results
