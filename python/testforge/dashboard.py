"""Single-file static dashboard server.

A tiny FastAPI app that serves:
    /                - list of recent builds
    /build/{id}      - per-build summary, results, clusters

No JS framework, no build step. Just Jinja2 templates served from memory.
Run with: `python -m testforge.dashboard` or `testforge dashboard`.
"""

from __future__ import annotations

import html
from pathlib import Path

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


def create_app(storage, config):
    if not _HAS_FASTAPI:
        raise RuntimeError(
            "dashboard requires fastapi. Install with: pip install testforge[dashboard]")

    app = FastAPI(title="TestForge Dashboard", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        builds = _list_builds(storage)
        rows = "\n".join(
            f"<tr><td><a href='/build/{b['id']}'>#{b['id']}</a></td>"
            f"<td>{b.get('status') or 'running'}</td>"
            f"<td>{b.get('total_tests') or 0}</td>"
            f"<td>{b.get('passed') or 0}</td>"
            f"<td>{b.get('failed') or 0}</td>"
            f"<td>{b.get('flaky') or 0}</td>"
            f"<td>{b.get('started_at','')}</td></tr>"
            for b in builds
        )
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>TestForge</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ padding: .4em .6em; border-bottom: 1px solid #eee; text-align: left; }}
th {{ background: #fafafa; }}
</style></head><body>
<h1>TestForge</h1>
<h2>Builds</h2>
<table>
<tr><th>Build</th><th>Status</th><th>Total</th><th>Passed</th><th>Failed</th><th>Flaky</th><th>Started</th></tr>
{rows}
</table>
</body></html>"""

    @app.get("/build/{build_id}", response_class=HTMLResponse)
    def build_view(build_id: int):
        results = storage.get_results(build_id)
        clusters = storage.get_clusters(build_id)
        rows = "\n".join(
            f"<tr class='{r.status}'><td>{html.escape(r.test_name)}</td>"
            f"<td>{r.status}</td>"
            f"<td>{r.duration_ms:.2f}</td>"
            f"<td>{r.peak_rss_kb or '-'}</td>"
            f"<td>{r.gpu_kernel_latency_ms or '-'}</td>"
            f"<td>{html.escape((r.failure_message or '')[:80])}</td></tr>"
            for r in results
        )
        cluster_rows = "\n".join(
            f"<div class='cluster'><b>{c['count']} failures</b> "
            f"- {html.escape(c.get('component') or '?')}<br>"
            f"<code>{html.escape(c.get('sample_message') or '')[:200]}</code></div>"
            for c in clusters
        )
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Build #{build_id}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 2em auto; padding: 0 1em; }}
table {{ border-collapse: collapse; width: 100%; font-size: .9em; }}
th, td {{ padding: .4em .6em; border-bottom: 1px solid #eee; text-align: left; }}
th {{ background: #fafafa; }}
tr.fail td {{ color: #c93a3a; }}
tr.flaky td {{ color: #c98200; }}
.cluster {{ background: #fff8e0; padding: .6em 1em; margin: .5em 0; border-left: 4px solid #c98200; }}
</style></head><body>
<h1>Build #{build_id}</h1>
<p><a href="/">← back to builds</a></p>
<h2>Results</h2>
<table>
<tr><th>Test</th><th>Status</th><th>Duration (ms)</th><th>RSS (KB)</th><th>GPU ms</th><th>Failure</th></tr>
{rows}
</table>
<h2>Failure clusters</h2>
{cluster_rows or '<p class="muted">none</p>'}
</body></html>"""

    return app


def _list_builds(storage, limit: int = 50):
    # We use sqlite3 directly because StorageBackend doesn't expose builds,
    # only results. That's intentional - the dashboard is storage-aware.
    import sqlite3
    if not hasattr(storage, "_conn"):
        return []
    conn = storage._conn
    cur = conn.execute(
        "SELECT * FROM builds ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]


def run_dashboard(storage, config, host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    app = create_app(storage, config)
    uvicorn.run(app, host=host, port=port, log_level="warning")
