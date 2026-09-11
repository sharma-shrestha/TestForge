"""testforge CLI entry point.

Implements the user-facing commands:
    init        - scaffold .testforge/config.yaml
    discover    - list discovered tests
    run         - run tests (optionally filtered by changed files, suite, etc.)
    analyze     - analyze the latest (or specified) build: regressions, flaky, clusters
    benchmark   - run a target N times, report latency stats
    report      - render HTML or terminal report for a build
    dashboard   - start the local dashboard server

Each command is implemented as a Click subcommand for discoverability.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import click

from testforge.config import Config
from testforge.discovery import discover_tests
from testforge.dependency_graph import DependencyGraph
from testforge.flaky import scan_flaky
from testforge.gpu_metrics import GPUMetricsCollector
from testforge.regression import detect_regressions
from testforge.clustering import cluster_failures
from testforge.scheduler import run_tests_parallel
from testforge.selection import score_tests
from testforge.storage import open_storage, SQLiteBackend
from testforge.reporter import render_terminal, render_html
from testforge.assistant import FailureAnalyst


def _load_config():
    return Config.load(Path.cwd())


@click.group()
@click.version_option()
def cli():
    """TestForge - distributed test automation & GPU validation framework."""


@cli.command()
def init():
    """Initialize a TestForge project in the current directory."""
    cfg_dir = Path.cwd() / ".testforge"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg = Config(project_root=Path.cwd())
    cfg.save()

    click.echo(f"Created {cfg_dir / 'config.yaml'}")
    click.echo("Edit it to point at your worker binary, then run "
               "`testforge discover`.")


@cli.command()
@click.option("--root", default=".", help="Project root to discover tests in.")
def discover(root):
    """List discovered tests."""
    config = _load_config()
    specs = discover_tests(Path(root))
    if not specs:
        click.echo("(no tests found - build the C++ engine first or add a tests.yaml)")
        return
    click.echo(f"{len(specs)} test(s) discovered:")
    for s in specs:
        click.echo(f"  {s.name:40s}  {s.kind:12s}  {s.type:6s}  {s.component}")


@cli.command()
@click.option("--root", default=".", help="Project root.")
@click.option("--suite", default=None, help="Only run tests in this suite.")
@click.option("--tag", default=None, help="Only run tests with this tag.")
@click.option("--changed-files", "changed_files", default=None,
              help="Comma-separated list of changed files; selects relevant tests.")
@click.option("--workers", default=None, type=int,
              help="Number of parallel workers (default: cpu count).")
@click.option("--top-k", default=None, type=int,
              help="Run only the top-K scored tests (used with --changed-files).")
@click.option("--assistant", is_flag=True, default=False,
              help="Enable LLM-backed failure analyst (requires config).")
@click.option("--html", "html_path", default=None,
              help="Write an HTML report to this path after the run.")
def run(root, suite, tag, changed_files, workers, top_k, assistant, html_path):
    """Run tests."""
    config = _load_config()
    if workers is not None:
        config.default_workers = workers

    specs = discover_tests(Path(root))
    if suite:
        specs = [s for s in specs if s.suite == suite]
    if tag:
        specs = [s for s in specs if tag in s.tags]
    if not specs:
        click.echo("no tests matched.")
        return

    storage = open_storage(config)

    # If --changed-files was given, narrow to relevant tests via the
    # dependency graph and (optionally) the selection scorer.
    changed_components: set[str] = set()
    if changed_files:
        graph = DependencyGraph.from_manifest(
            config.project_root / ".testforge" / "dependencies.yaml")
        files = [f.strip() for f in changed_files.split(",")]
        specs = graph.relevant_tests(specs, files)
        changed_components = graph.relevant_components(files)
        if not specs:
            click.echo("(no tests are relevant to the changed files)")
            return

    # Score and select top-K if requested.
    if top_k and top_k > 0 and changed_files:
        scored = score_tests(specs, storage,
                              changed_components=changed_components,
                              weights=config.selection)
        click.echo(f"Selected top-{top_k} of {len(specs)} tests by score:")
        for s in scored[:top_k]:
            click.echo(f"  {s.score:.3f}  {s.test.name}")
        specs = [s.test for s in scored[:top_k]]

    git_sha = _git_sha(config.project_root)
    branch  = _git_branch(config.project_root)
    build_id = storage.create_build(git_sha=git_sha, branch=branch,
                                     worker_count=config.default_workers,
                                     notes=f"selected {len(specs)} tests")

    click.echo(f"Starting build #{build_id} with {len(specs)} test(s) "
               f"across {config.default_workers or os.cpu_count()} workers.")

    gpu_collector = GPUMetricsCollector(config.gpu_smi_path) if config.gpu_metrics_enabled else None
    if gpu_collector and gpu_collector.is_available():
        snap = gpu_collector.snapshot()
        click.echo(f"GPU detected: {snap.device_name} "
                   f"({snap.memory_used_mb}MB / {snap.memory_total_mb}MB)")

    results = run_tests_parallel(specs, config, build_id, storage)

    # Detect regressions, clusters, flakiness.
    regressions = detect_regressions(results, storage, config.regression)
    clusters = cluster_failures(results)
    for c in clusters:
        storage.store_cluster(build_id, c.signature, c.component,
                               c.sample_message, c.count)

    # Optional LLM-backed failure analyst.
    analyst_reports = []
    if assistant:
        analyst = FailureAnalyst(config.assistant)
        if not analyst.available:
            click.echo("(assistant requested but not configured; skipping)")
        for c in clusters:
            history = [
                {"test_name": t, "build_id": build_id,
                 "failure_message": c.sample_message}
                for t in c.test_names[:5]
            ]
            ar = analyst.analyze(
                failure_message=c.sample_message,
                stack_trace="",
                test_name=c.test_names[0] if c.test_names else "?",
                component=c.component,
                tags=[],
                similar_history=history,
            )
            if ar.available:
                analyst_reports.append({
                    "test_name": c.test_names[0] if c.test_names else "?",
                    "likely_cause": ar.likely_cause,
                    "confidence": ar.confidence,
                    "suggested_investigation": ar.suggested_investigation,
                })

    # Update build status.
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status in ("fail", "timeout"))
    flaky  = sum(1 for r in results if r.status == "flaky")
    status = "failed" if (failed or regressions) else "passed"
    storage.finish_build(build_id, status=status,
                          total=len(results), passed=passed,
                          failed=failed, flaky=flaky, skipped=0)

    # Print terminal report.
    click.echo("")
    click.echo(render_terminal(build_id, results, regressions, clusters))

    if html_path:
        render_html(build_id, results, regressions, clusters,
                    analyst_reports, html_path)
        click.echo(f"HTML report written to {html_path}")


@cli.command()
@click.option("--build", "build_id", default=None, type=int,
              help="Build to analyze (default: latest).")
@click.option("--assistant", is_flag=True, default=False,
              help="Enable LLM-backed failure analyst.")
def analyze(build_id, assistant):
    """Analyze a build: regressions, flaky tests, failure clusters."""
    config = _load_config()
    storage = open_storage(config)
    if build_id is None:
        build_id = _latest_build(storage)
        if build_id is None:
            click.echo("no builds found.")
            return
    results = storage.get_results(build_id)
    if not results:
        click.echo(f"build #{build_id} has no results.")
        return
    regressions = detect_regressions(results, storage, config.regression)
    clusters = cluster_failures(results)
    flaky = scan_flaky(list({r.test_name for r in results}), storage,
                       threshold=config.flaky_threshold)
    click.echo(render_terminal(build_id, results, regressions, clusters))
    if flaky:
        click.echo("\n--- Flaky tests ---")
        for f in flaky:
            if f.flakiness > 0:
                click.echo(f"  {f.test_name:40s}  flaky={f.flakiness:.2f} "
                           f"({'QUARANTINED' if f.quarantined else 'ok'})  "
                           f"sample={f.sample_size}")


@cli.command()
@click.option("--build", "build_id", default=None, type=int,
              help="Build to report on (default: latest).")
@click.option("--html", "html_path", default=None,
              help="Write HTML report to this path.")
def report(build_id, html_path):
    """Render a report for a build."""
    config = _load_config()
    storage = open_storage(config)
    if build_id is None:
        build_id = _latest_build(storage)
        if build_id is None:
            click.echo("no builds found.")
            return
    results = storage.get_results(build_id)
    regressions = detect_regressions(results, storage, config.regression)
    clusters = cluster_failures(results)
    if html_path:
        render_html(build_id, results, regressions, clusters, [], html_path)
        click.echo(f"HTML report written to {html_path}")
    else:
        click.echo(render_terminal(build_id, results, regressions, clusters))


@cli.command()
@click.argument("test_name")
@click.option("--n", default=20, help="Number of iterations.")
@click.option("--metric", default="duration_ms",
              help="Metric to report on (duration_ms, peak_rss_kb, etc.).")
def benchmark(test_name, n, metric):
    """Run a test N times and report latency stats."""
    config = _load_config()
    specs = discover_tests(config.project_root)
    target = next((s for s in specs if s.name == test_name), None)
    if not target:
        click.echo(f"no such test: {test_name}")
        return
    storage = open_storage(config)
    build_id = storage.create_build(git_sha="", branch="",
                                     worker_count=1, notes=f"benchmark {test_name} x{n}")
    click.echo(f"Running {test_name} {n} times...")
    times = []
    for i in range(n):
        click.echo(f"  iter {i+1}/{n}...", nl=False)
        results = run_tests_parallel([target], config, build_id, storage)
        if results:
            v = getattr(results[0], metric, None)
            if v is not None:
                times.append(float(v))
                click.echo(f"  {v:.3f}")
            else:
                click.echo("  (no metric)")
        else:
            click.echo("  (no result)")
    if times:
        times.sort()
        median = times[len(times)//2]
        p95 = times[int(len(times) * 0.95)] if len(times) >= 20 else times[-1]
        p99 = times[int(len(times) * 0.99)] if len(times) >= 100 else times[-1]
        click.echo(f"\n{metric}:")
        click.echo(f"  min     {times[0]:.3f}")
        click.echo(f"  median  {median:.3f}")
        click.echo(f"  p95     {p95:.3f}")
        click.echo(f"  p99     {p99:.3f}")
        click.echo(f"  max     {times[-1]:.3f}")


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
def dashboard(host, port):
    """Start the local dashboard web server."""
    config = _load_config()
    storage = open_storage(config)
    from testforge.dashboard import run_dashboard
    click.echo(f"Dashboard: http://{host}:{port}")
    run_dashboard(storage, config, host=host, port=port)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git_sha(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=root, capture_output=True, text=True, timeout=2)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _git_branch(root: Path) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=root, capture_output=True, text=True, timeout=2)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _latest_build(storage) -> int | None:
    if isinstance(storage, SQLiteBackend):
        cur = storage._conn.execute(
            "SELECT id FROM builds ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None
    # PostgresBackend: same idea, different conn
    with storage.conn.cursor() as cur:
        cur.execute("SELECT id FROM builds ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


if __name__ == "__main__":
    cli()
