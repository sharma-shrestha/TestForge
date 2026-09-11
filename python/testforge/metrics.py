"""Prometheus metrics endpoint.

Exposes a single `/metrics` endpoint with counters and histograms for
the orchestrator's activity. Intended to be scraped by Prometheus and
visualized in Grafana.

Metrics exposed:

    testforge_tests_total{status}             counter
    testforge_tests_failed                    counter
    testforge_test_duration_seconds{test}     histogram
    testforge_worker_failures                 counter
    testforge_gpu_execution_seconds{test}     histogram
    testforge_regressions_detected{kind}      counter
    testforge_builds_total{status}           counter
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class MetricsRegistry:
    counters: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    histograms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, name: str, value: float = 1.0, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.counters[key] += value

    def observe(self, name: str, value: float, **labels) -> None:
        key = self._key(name, labels)
        with self._lock:
            self.histograms[key].append(value)
            # Cap each histogram at 1000 samples to bound memory.
            if len(self.histograms[key]) > 1000:
                self.histograms[key] = self.histograms[key][-1000:]

    def _key(self, name: str, labels: dict) -> str:
        if not labels:
            return name
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return f"{name}{{{','.join(parts)}}}"

    def render(self) -> str:
        with self._lock:
            lines = []
            for key, val in sorted(self.counters.items()):
                lines.append(f"{key} {val}")
            for key, samples in sorted(self.histograms.items()):
                if not samples:
                    continue
                sorted_s = sorted(samples)
                n = len(sorted_s)
                p50 = sorted_s[n // 2]
                p95 = sorted_s[int(n * 0.95)] if n >= 20 else sorted_s[-1]
                p99 = sorted_s[int(n * 0.99)] if n >= 100 else sorted_s[-1]
                lines.append(f'{key}_count {n}')
                lines.append(f'{key}_sum {sum(samples):.6f}')
                lines.append(f'{key}{{quantile="0.5"}} {p50:.6f}')
                lines.append(f'{key}{{quantile="0.95"}} {p95:.6f}')
                lines.append(f'{key}{{quantile="0.99"}} {p99:.6f}')
            return "\n".join(lines) + "\n"


# Global registry (single-process orchestrator).
REGISTRY = MetricsRegistry()


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = REGISTRY.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silence stderr logging


def run_metrics_server(port: int = 9100, host: str = "127.0.0.1"):
    server = ThreadingHTTPServer((host, port), MetricsHandler)
    server.serve_forever()


def start_metrics_server_in_background(port: int = 9100):
    t = threading.Thread(target=run_metrics_server, args=(port,), daemon=True)
    t.start()
    return t
