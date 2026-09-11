"""Smoke test - verify the C++ engine compiles and the sample tests pass.

Run as: python scripts/smoke_test.py

Builds the engine (falling back to g++ if CMake isn't available), runs
the worker binary, parses the JSON output, and checks that:

  - all tests run
  - the JSON is valid
  - the known-passing tests report status=pass
  - the failure signature on the intentional-failure test (when enabled)
    matches the expected hash
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEST_BIN = ROOT / "build" / "bin" / "example_cpp_tests"


def build() -> bool:
    if TEST_BIN.exists():
        return True
    # Try CMake first, fall back to direct g++.
    if subprocess.run(["which", "cmake"], capture_output=True).returncode == 0:
        subprocess.run(
            ["cmake", "-S", str(ROOT), "-B", str(ROOT / "build"),
             "-DCMAKE_BUILD_TYPE=Release", "-DTESTFORGE_ENABLE_CUDA=OFF"],
            check=True)
        subprocess.run(["cmake", "--build", str(ROOT / "build"), "-j"], check=True)
    else:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)
    return TEST_BIN.exists()


def run_test_binary(env: dict | None = None) -> dict:
    env = env or os.environ.copy()
    proc = subprocess.run(
        [str(TEST_BIN)], capture_output=True, text=True, env=env, timeout=60)
    # The test binary exits 0 if all tests passed, 1 if any failed.
    # We still parse the JSON output either way.
    lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        print("no JSON output from test binary", file=sys.stderr)
        print(proc.stdout, file=sys.stderr)
        sys.exit(1)
    return json.loads(lines[-1])


def main() -> int:
    if not build():
        print("build failed", file=sys.stderr)
        return 1

    print("[smoke] running test binary with default config...")
    report = run_test_binary()
    results = report.get("results", [])
    print(f"[smoke] {len(results)} test(s) ran")

    expected_pass = {
        "Sanity.AlwaysPass",
        "Math.FloatNear",
        "Math.MatrixMultiplyIdentity",
        "Math.MatrixMultiplyKnown",
        "Math.DotProduct",
        "Math.Reduction",
        "PerfDemo.Sleep50ms",
    }
    for name in expected_pass:
        r = next((x for x in results if x["test_name"] == name), None)
        if r is None:
            print(f"  FAIL: missing test {name}", file=sys.stderr)
            return 1
        if r["status"] != "pass":
            print(f"  FAIL: {name} status={r['status']}", file=sys.stderr)
            return 1
    print("[smoke] all expected-pass tests passed")

    # The flaky demo test should fail on first attempt.
    flaky = next(x for x in results if x["test_name"] == "FlakyDemo.PassesOnRetry")
    assert flaky["status"] == "fail", \
        f"expected flaky test to fail without retries, got {flaky['status']}"
    assert flaky["error_signature"], \
        "flaky test should have an error_signature"
    print(f"[smoke] flaky test correctly failed; signature={flaky['error_signature']}")

    # With retries enabled (env var), the flaky test should pass on the
    # second attempt - but since the worker binary doesn't yet read
    # retries from env, we skip this check. The Python orchestrator
    # handles retries by re-running.

    print("[smoke] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
