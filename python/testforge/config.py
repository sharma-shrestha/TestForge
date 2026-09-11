"""Configuration loading.

A TestForge project has a `.testforge/config.yaml` (created by `testforge init`)
that specifies:
    - storage backend (sqlite path, postgres DSN)
    - worker binary path
    - default worker count
    - regression thresholds (perf %, memory %, flaky score)
    - dependency graph source
    - assistant (LLM) endpoint, optional

Anything not specified falls back to a sensible default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RegressionThresholds:
    perf_pct: float = 10.0          # fail if latency worsens by >10%
    memory_pct: float = 25.0        # fail if peak RSS worsens by >25%
    gpu_latency_pct: float = 10.0
    gpu_memory_pct: float = 25.0


@dataclass
class SelectionWeights:
    dependency_relevance: float = 0.30
    historical_failure_rate: float = 0.25
    recent_failure_frequency: float = 0.20
    performance_impact: float = 0.15
    execution_cost: float = 0.10       # penalty for slow tests


@dataclass
class AssistantConfig:
    enabled: bool = False
    base_url: str = ""               # any OpenAI-compatible /v1 endpoint
    api_key_env: str = ""            # name of env var holding the API key
    model: str = "gpt-4o-mini"
    max_tokens: int = 600
    timeout_seconds: float = 30.0


@dataclass
class Config:
    project_root: Path = Path(".")
    storage: dict = field(default_factory=lambda: {
        "backend": "sqlite",
        "sqlite_path": ".testforge/testforge.db",
    })
    # Default test binary to use when discovery doesn't find one. In v0.5+
    # each test binary IS a worker (links libtestforge_core + calls
    # testforge_main), so this is just a fallback path for the discovery
    # step, not a separate "worker" binary.
    test_binary: str = "build/bin/example_cpp_tests"
    default_workers: int = 0          # 0 = os.cpu_count()
    default_retries: int = 0
    regression: RegressionThresholds = field(default_factory=RegressionThresholds)
    selection: SelectionWeights = field(default_factory=SelectionWeights)
    flaky_threshold: float = 0.15     # quarantine if flaky_score > 0.15
    assistant: AssistantConfig = field(default_factory=AssistantConfig)
    gpu_metrics_enabled: bool = True
    gpu_smi_path: str = "nvidia-smi"

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Config":
        root = (project_root or Path.cwd()).resolve()
        cfg_path = root / ".testforge" / "config.yaml"
        if not cfg_path.exists():
            return cls(project_root=root)
        with open(cfg_path) as f:
            data = yaml.safe_load(f) or {}
        cfg = cls(project_root=root)
        if "storage" in data:
            cfg.storage.update(data["storage"])
        if "test_binary" in data:
            cfg.test_binary = data["test_binary"]
        elif "worker_binary" in data:
            # Backward compat with v0.4 config files.
            cfg.test_binary = data["worker_binary"]
        if "default_workers" in data:
            cfg.default_workers = int(data["default_workers"])
        if "default_retries" in data:
            cfg.default_retries = int(data["default_retries"])
        if "flaky_threshold" in data:
            cfg.flaky_threshold = float(data["flaky_threshold"])
        if "regression" in data:
            for k, v in data["regression"].items():
                if hasattr(cfg.regression, k):
                    setattr(cfg.regression, k, float(v))
        if "selection" in data:
            for k, v in data["selection"].items():
                if hasattr(cfg.selection, k):
                    setattr(cfg.selection, k, float(v))
        if "assistant" in data:
            for k, v in data["assistant"].items():
                if hasattr(cfg.assistant, k):
                    setattr(cfg.assistant, k, v)
        if "gpu_metrics_enabled" in data:
            cfg.gpu_metrics_enabled = bool(data["gpu_metrics_enabled"])
        return cfg

    def save(self) -> None:
        cfg_dir = self.project_root / ".testforge"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "storage": self.storage,
            "test_binary": self.test_binary,
            "default_workers": self.default_workers,
            "default_retries": self.default_retries,
            "flaky_threshold": self.flaky_threshold,
            "regression": self.regression.__dict__,
            "selection": self.selection.__dict__,
            "gpu_metrics_enabled": self.gpu_metrics_enabled,
            "assistant": {
                "enabled": self.assistant.enabled,
                "base_url": self.assistant.base_url,
                "api_key_env": self.assistant.api_key_env,
                "model": self.assistant.model,
                "max_tokens": self.assistant.max_tokens,
                "timeout_seconds": self.assistant.timeout_seconds,
            },
        }
        with open(cfg_dir / "config.yaml", "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)
