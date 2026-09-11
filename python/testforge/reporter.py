"""Report rendering: terminal + HTML.

The HTML report is a single self-contained file (no external CSS/JS) so
it can be attached to an email, dropped on a static host, or opened from
the filesystem. Built with Jinja2.

The terminal report uses `rich` for table formatting and colored status
indicators. If rich isn't installed, falls back to plain text.
"""

from __future__ import annotations

import html as html_lib
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .clustering import FailureCluster
from .regression import Regression
from .storage import StoredResult

try:
    from rich.console import Console
    from rich.table import Table
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TestForge Build #{{ build_id }} Report</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 1100px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1, h2, h3 { font-weight: 600; }
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1em; margin: 1em 0 2em; }
  .card { background: #f7f7f7; padding: 1em; border-radius: 4px; border-left: 4px solid #888; }
  .card.pass    { border-color: #2c8a3a; }
  .card.fail    { border-color: #c93a3a; }
  .card.flaky   { border-color: #c98200; }
  .card.metric  { border-color: #2a6fb0; }
  .card h3 { margin: 0 0 .25em; font-size: .8em; text-transform: uppercase;
             color: #666; letter-spacing: .05em; }
  .card .value { font-size: 1.6em; font-weight: 600; }
  table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }
  th, td { padding: .4em .6em; text-align: left; border-bottom: 1px solid #eee; }
  th { background: #fafafa; font-weight: 600; }
  tr.fail td { color: #c93a3a; }
  tr.flaky td { color: #c98200; }
  .status { display: inline-block; padding: .1em .5em; border-radius: 3px;
            font-size: .8em; font-weight: 600; }
  .status.pass    { background: #d6eed8; color: #2c8a3a; }
  .status.fail    { background: #f5d6d6; color: #c93a3a; }
  .status.timeout { background: #f5e0c8; color: #b06000; }
  .status.flaky   { background: #fbe6b8; color: #c98200; }
  .cluster { background: #fff8e0; border-left: 4px solid #c98200;
             padding: .6em 1em; margin: .5em 0; border-radius: 3px; }
  .assistant { background: #f0f4ff; border-left: 4px solid #2a6fb0;
               padding: .6em 1em; margin: .5em 0; border-radius: 3px;
               font-size: .9em; }
  .assistant .label { font-weight: 600; color: #2a6fb0; }
  .muted { color: #888; font-size: .85em; }
</style>
</head>
<body>
<h1>TestForge Build #{{ build_id }}</h1>
<p class="muted">Generated {{ generated_at }}</p>

<h2>Summary</h2>
<div class="summary">
  <div class="card pass"><h3>Passed</h3><div class="value">{{ passed }}</div></div>
  <div class="card fail"><h3>Failed</h3><div class="value">{{ failed }}</div></div>
  <div class="card flaky"><h3>Flaky</h3><div class="value">{{ flaky }}</div></div>
  <div class="card metric"><h3>Total</h3><div class="value">{{ total }}</div></div>
</div>

{% if regressions %}
<h2>Regressions</h2>
<table>
<tr><th>Test</th><th>Kind</th><th>Metric</th><th>Baseline</th><th>Current</th><th>Delta</th><th>Threshold</th></tr>
{% for r in regressions %}
<tr><td>{{ r.test_name }}</td><td>{{ r.kind }}</td><td>{{ r.metric }}</td>
    <td>{{ "%.3f"|format(r.baseline) }}</td><td>{{ "%.3f"|format(r.current) }}</td>
    <td>+{{ "%.2f"|format(r.delta_pct) }}%</td><td>{{ r.threshold_pct }}%</td></tr>
{% endfor %}
</table>
{% endif %}

{% if clusters %}
<h2>Failure clusters</h2>
{% for c in clusters %}
<div class="cluster">
  <strong>{{ c.count }} failure(s)</strong> - {{ c.component or "unknown component" }}<br>
  <span class="muted">signature: {{ c.signature }}</span><br>
  <code>{{ c.sample_message }}</code>
  <ul class="muted">
  {% for t in c.test_names[:10] %}<li>{{ t }}</li>{% endfor %}
  {% if c.test_names|length > 10 %}<li>... and {{ c.test_names|length - 10 }} more</li>{% endif %}
  </ul>
</div>
{% endfor %}
{% endif %}

{% if analyst_reports %}
<h2>Assistant analysis</h2>
{% for ar in analyst_reports %}
<div class="assistant">
  <span class="label">{{ ar.test_name }}</span><br>
  <strong>Likely cause:</strong> {{ ar.likely_cause }}<br>
  <strong>Confidence:</strong> {{ "%.0f"|format(ar.confidence * 100) }}%<br>
  {% if ar.suggested_investigation %}
  <strong>Suggested investigation:</strong>
  <ul>{% for s in ar.suggested_investigation %}<li>{{ s }}</li>{% endfor %}</ul>
  {% endif %}
</div>
{% endfor %}
{% endif %}

<h2>All results</h2>
<table>
<tr><th>Test</th><th>Status</th><th>Duration (ms)</th><th>Attempts</th><th>RSS (KB)</th><th>GPU latency (ms)</th></tr>
{% for r in results %}
<tr class="{{ r.status }}">
  <td>{{ r.test_name }}</td>
  <td><span class="status {{ r.status }}">{{ r.status }}</span></td>
  <td>{{ "%.2f"|format(r.duration_ms) }}</td>
  <td>{{ r.attempts }}</td>
  <td>{{ r.peak_rss_kb if r.peak_rss_kb is not none else "-" }}</td>
  <td>{{ "%.2f"|format(r.gpu_kernel_latency_ms) if r.gpu_kernel_latency_ms else "-" }}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""


def render_terminal(
    build_id: int,
    results: list[StoredResult],
    regressions: list[Regression] = None,
    clusters: list[FailureCluster] = None,
) -> str:
    regressions = regressions or []
    clusters = clusters or []
    if not _HAS_RICH:
        return _render_plain(build_id, results, regressions, clusters)

    console = Console(record=True, force_terminal=False)
    table = Table(title=f"TestForge Build #{build_id}")
    table.add_column("Test")
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right")
    table.add_column("Attempts", justify="right")
    table.add_column("RSS (KB)", justify="right")
    table.add_column("GPU ms", justify="right")

    status_style = {
        "pass": "green", "fail": "red", "timeout": "yellow",
        "flaky": "yellow", "skipped": "dim", "not_run": "dim",
    }
    for r in results:
        table.add_row(
            r.test_name,
            f"[{status_style.get(r.status, 'white')}]{r.status}[/{status_style.get(r.status, 'white')}]",
            f"{r.duration_ms:.2f}",
            str(r.attempts),
            str(r.peak_rss_kb) if r.peak_rss_kb is not None else "-",
            f"{r.gpu_kernel_latency_ms:.2f}" if r.gpu_kernel_latency_ms else "-",
        )
    console.print(table)

    if regressions:
        rtable = Table(title="Regressions")
        rtable.add_column("Test")
        rtable.add_column("Kind")
        rtable.add_column("Metric")
        rtable.add_column("Delta", justify="right")
        for r in regressions:
            rtable.add_row(r.test_name, r.kind, r.metric,
                            f"+{r.delta_pct:.2f}%")
        console.print(rtable)

    if clusters:
        ctable = Table(title="Failure clusters")
        ctable.add_column("Component")
        ctable.add_column("Count", justify="right")
        ctable.add_column("Sample message")
        for c in clusters:
            ctable.add_row(c.component or "?", str(c.count),
                            c.sample_message[:80])
        console.print(ctable)

    return console.export_text()


def _render_plain(build_id, results, regressions, clusters):
    lines = [f"=== TestForge Build #{build_id} ==="]
    for r in results:
        lines.append(f"  [{r.status:8s}] {r.test_name:40s} "
                     f"{r.duration_ms:8.2f}ms  attempts={r.attempts}")
    if regressions:
        lines.append("\n--- Regressions ---")
        for r in regressions:
            lines.append(f"  {r.test_name} {r.kind} {r.metric} +{r.delta_pct:.2f}%")
    if clusters:
        lines.append("\n--- Clusters ---")
        for c in clusters:
            lines.append(f"  {c.component}: {c.count} failures - {c.sample_message[:60]}")
    return "\n".join(lines)


def render_html(
    build_id: int,
    results: list[StoredResult],
    regressions: list[Regression] = None,
    clusters: list[FailureCluster] = None,
    analyst_reports: list[dict] = None,
    output_path: Path | str = None,
) -> str:
    from jinja2 import Template
    regressions = regressions or []
    clusters = clusters or []
    analyst_reports = analyst_reports or []

    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status in ("fail", "timeout"))
    flaky  = sum(1 for r in results if r.status == "flaky")
    total  = len(results)

    # Sanitize all string fields before rendering (avoid HTML injection from
    # failure messages - they're free-form text from test binaries).
    def esc(s):
        return html_lib.escape(str(s)) if s is not None else ""

    sanitized_results = [
        type("R", (), {
            "test_name": esc(r.test_name),
            "status": esc(r.status),
            "duration_ms": r.duration_ms,
            "attempts": r.attempts,
            "peak_rss_kb": r.peak_rss_kb,
            "gpu_kernel_latency_ms": r.gpu_kernel_latency_ms,
        })() for r in results
    ]
    sanitized_regs = [
        type("Reg", (), {
            "test_name": esc(r.test_name),
            "kind": esc(r.kind),
            "metric": esc(r.metric),
            "baseline": r.baseline,
            "current": r.current,
            "delta_pct": r.delta_pct,
            "threshold_pct": r.threshold_pct,
        })() for r in regressions
    ]
    sanitized_clusters = [
        type("C", (), {
            "signature": esc(c.signature),
            "component": esc(c.component),
            "sample_message": esc(c.sample_message),
            "count": c.count,
            "test_names": c.test_names,
        })() for c in clusters
    ]
    sanitized_analyst = [
        {"test_name": esc(a.get("test_name", "")),
         "likely_cause": esc(a.get("likely_cause", "")),
         "confidence": float(a.get("confidence", 0.0)),
         "suggested_investigation": [esc(s) for s in a.get("suggested_investigation", [])]}
        for a in analyst_reports
    ]

    tmpl = Template(HTML_TEMPLATE)
    rendered = tmpl.render(
        build_id=build_id,
        generated_at=datetime.utcnow().isoformat() + "Z",
        passed=passed, failed=failed, flaky=flaky, total=total,
        results=sanitized_results,
        regressions=sanitized_regs,
        clusters=sanitized_clusters,
        analyst_reports=sanitized_analyst,
    )

    if output_path:
        Path(output_path).write_text(rendered, encoding="utf-8")
    return rendered
