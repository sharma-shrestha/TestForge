"""Test discovery.

Walks the project looking for test binaries and per-test metadata files,
builds a list of TestSpec objects the scheduler can consume.

We support two flavors of test:

  1. Tests registered with the C++ TestForge engine (compiled into a binary
     that exposes them via `--list`). The worker binary enumerates them.

  2. Standalone test binaries (GoogleTest, ctest, or any executable that
     emits results in a known format). For these we read a sidecar
     `tests.yaml` manifest describing what to run.

  3. pytest tests. We walk for files matching `test_*.py` and treat each
     test function as a TestSpec. (Lightweight: we don't actually parse
     pytest internals, we just `pytest --co -q` the file to enumerate.)
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class TestSpec:
    """A single test the orchestrator can schedule.

    `kind` is one of:
        - "cpp_engine"   : registered with the C++ TestForge engine
        - "pytest"       : a pytest test function
        - "binary"       : a standalone test binary (gtest, etc.)

    `binary` is the path to the test binary. For cpp_engine tests, it's the
    test binary itself (which links libtestforge_core and calls
    testforge_main - there is no separate worker binary). For pytest
    tests, it's the path to the test file. For binary tests, it's the
    executable path.
    """
    # Tell pytest not to collect this dataclass as a test class (it starts
    # with "Test" so pytest tries to, which produces a warning).
    __test__ = False

    name: str
    suite: str = ""
    kind: str = "cpp_engine"
    binary: str = ""
    component: str = ""
    type: str = "cpu"           # cpu | gpu | integration
    priority: str = "normal"   # low | normal | high
    timeout_ms: int = 30000
    retries: int = 0
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_tests(root: Path) -> list[TestSpec]:
    """Discover tests under `root`.

    Looks for:
      - C++ binaries built under <root>/build/bin/ that link with the engine
        and register tests via the TEST() macro
      - `tests.yaml` manifests (per-directory) describing standalone tests
      - pytest test files (test_*.py)
    """
    specs: list[TestSpec] = []

    # 1. C++ engine tests: ask each binary under build/bin/ to --list itself.
    build_bin = root / "build" / "bin"
    if build_bin.is_dir():
        for b in sorted(build_bin.iterdir()):
            if not b.is_file() or not os.access(b, os.X_OK):
                continue
            specs.extend(_discover_from_engine_binary(b))

    # 2. tests.yaml manifests.
    for manifest in root.rglob("tests.yaml"):
        specs.extend(_discover_from_manifest(manifest))

    # 3. pytest tests.
    for f in root.rglob("test_*.py"):
        specs.extend(_discover_from_pytest_file(f))

    # Deduplicate by name (later sources win, so manifests can override
    # autodiscovered entries).
    by_name: dict[str, TestSpec] = {}
    for s in specs:
        by_name[s.name] = s
    return list(by_name.values())


def _discover_from_engine_binary(binary: Path) -> list[TestSpec]:
    try:
        out = subprocess.run(
            [str(binary), "--list"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    specs: list[TestSpec] = []
    for line in out.stdout.splitlines():
        # Format: "Suite.Name<TAB>cpu<TAB>component"
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        if not name or "." not in name:
            continue
        suite = name.split(".", 1)[0]
        kind = parts[1].strip() if len(parts) > 1 else "cpu"
        component = parts[2].strip() if len(parts) > 2 else ""
        specs.append(TestSpec(
            name=name,
            suite=suite,
            kind="cpp_engine",
            binary=str(binary),
            type=kind,
            component=component,
        ))
    return specs


def _discover_from_manifest(path: Path) -> list[TestSpec]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    tests = data.get("tests", [])
    specs: list[TestSpec] = []
    base_dir = path.parent
    for t in tests:
        specs.append(TestSpec(
            name=t["name"],
            suite=t.get("suite", ""),
            kind=t.get("kind", "binary"),
            binary=str(base_dir / t["binary"]) if not t.get("binary","").startswith("/") else t["binary"],
            component=t.get("component", ""),
            type=t.get("type", "cpu"),
            priority=t.get("priority", "normal"),
            timeout_ms=t.get("timeout_ms", 30000),
            retries=t.get("retries", 0),
            tags=t.get("tags", []),
            depends_on=t.get("depends_on", []),
        ))
    return specs


def _discover_from_pytest_file(path: Path) -> list[TestSpec]:
    try:
        out = subprocess.run(
            ["pytest", "--co", "-q", str(path)],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []
    specs: list[TestSpec] = []
    # pytest --co -q output: one test per line, format like
    #   tests/test_foo.py::test_bar
    pat = re.compile(r"^(?P<file>.+?)::(?P<func>test_\w+)\s*$")
    for line in out.stdout.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        f = m.group("file")
        func = m.group("func")
        specs.append(TestSpec(
            name=f"{Path(f).stem}.{func}",
            suite=Path(f).stem,
            kind="pytest",
            binary=str(path),
            type="cpu",
        ))
    return specs


# avoid late-import for os.access
import os  # noqa: E402
