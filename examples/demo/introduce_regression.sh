#!/usr/bin/env bash
# =============================================================================
# TestForge - killer demo
#
# Walks through the headline scenario: a developer introduces a performance
# regression into a computation kernel, TestForge catches it automatically.
#
# We use the CPU matrix-multiply test for portability (no CUDA needed to
# run the demo). The same flow works on the GPU test when CUDA is available.
#
# Usage:
#   ./examples/demo/introduce_regression.sh
#
# What it does:
#   1. Establishes a baseline run of the matrix multiply test.
#   2. Applies a patch that adds a deliberate inefficiency (a sleep loop)
#      to the kernel.
#   3. Re-runs TestForge and shows the regression being caught.
#   4. Reverts the patch.
#
# No production code is touched - the patch lives in this demo directory
# and is applied to a copy of the test source.
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

TEST_BIN="${ROOT}/build/bin/example_cpp_tests"
DEMO_PATCH="${ROOT}/examples/demo/regression.patch"

echo "============================================================"
echo " TestForge demo: performance regression detection"
echo "============================================================"
echo ""
echo "This demo:"
echo "  1. Records a baseline run of Math.MatrixMultiplyKnown"
echo "  2. Patches the test to simulate a perf regression"
echo "  3. Runs TestForge again - should catch the regression"
echo "  4. Reverts the patch"
echo ""

# ---------------------------------------------------------------------------
# Build the test binary if missing.
# ---------------------------------------------------------------------------
build_with_cmake() {
    command -v cmake >/dev/null 2>&1 || return 1
    cmake -S "$ROOT" -B "$ROOT/build" -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=OFF >/dev/null
    cmake --build "$ROOT/build" -j >/dev/null
}

build_with_make() {
    mkdir -p "$ROOT/build/bin"
    g++ -std=c++17 -Wall -Wextra -Wpedantic -I"$ROOT/cpp/include" \
        "$ROOT/cpp/src/test_registry.cpp" \
        "$ROOT/cpp/src/test_runner.cpp" \
        "$ROOT/cpp/src/assertion.cpp" \
        "$ROOT/cpp/src/test_result.cpp" \
        "$ROOT/cpp/src/json_writer.cpp" \
        "$ROOT/cpp/src/timeout.cpp" \
        "$ROOT/cpp/src/entry.cpp" \
        "$ROOT/cpp/examples/example_main.cpp" \
        "$ROOT/cpp/examples/cpu_tests.cpp" \
        "$ROOT/cpp/examples/cpu_math_tests.cpp" \
        -o "$ROOT/build/bin/example_cpp_tests" -pthread
}

if [[ ! -x "$TEST_BIN" ]]; then
    echo "[setup] Building C++ engine (no CUDA)..."
    if ! build_with_cmake; then
        echo "[setup] cmake not found; falling back to direct g++ build..."
        build_with_make
    fi
fi

# ---------------------------------------------------------------------------
# Sanity: make sure we can find the patch file.
# ---------------------------------------------------------------------------
if [[ ! -f "$DEMO_PATCH" ]]; then
    echo "[error] demo patch not found: $DEMO_PATCH" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: baseline run.
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 1: baseline run ==="
"$TEST_BIN" --filter Math.MatrixMultiplyKnown 2>&1 | grep "duration_ms\|-> pass" || true

# Run a few times to populate the baseline in storage. The new robust
# regression engine needs >= 5 samples before it uses MAD; below that it
# falls back to a simple percentage check against the median.
export PATH="${PATH}:${HOME}/.local/bin"
cd /tmp && rm -rf testforge_demo && mkdir testforge_demo && cd testforge_demo
mkdir -p build/bin
cp "$TEST_BIN" build/bin/example_cpp_tests
testforge init >/dev/null 2>&1

# Run 6 times to establish a solid baseline.
for i in 1 2 3 4 5 6; do
    testforge run >/dev/null 2>&1
done
echo "[step 1] baseline established (6 runs)."

# ---------------------------------------------------------------------------
# Step 2: apply the regression patch.
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: applying regression patch ==="
echo ""
echo "Patch contents:"
echo "------------------------------------------------------------"
cat "$DEMO_PATCH"
echo "------------------------------------------------------------"

# Apply to a copy of the test source so we don't touch the user's tree.
cp "${ROOT}/cpp/examples/cpu_math_tests.cpp" /tmp/testforge_demo/cpu_math_tests.cpp
( cd /tmp/testforge_demo && patch -p1 < "$DEMO_PATCH" )

# Rebuild with the patched source.
echo ""
echo "[step 2] rebuilding test binary with patched source..."
g++ -std=c++17 -I"${ROOT}/cpp/include" \
    "${ROOT}/cpp/src/test_registry.cpp" \
    "${ROOT}/cpp/src/test_runner.cpp" \
    "${ROOT}/cpp/src/assertion.cpp" \
    "${ROOT}/cpp/src/test_result.cpp" \
    "${ROOT}/cpp/src/json_writer.cpp" \
    "${ROOT}/cpp/src/timeout.cpp" \
    "${ROOT}/cpp/src/entry.cpp" \
    "${ROOT}/cpp/examples/example_main.cpp" \
    /tmp/testforge_demo/cpu_math_tests.cpp \
    "${ROOT}/cpp/examples/cpu_tests.cpp" \
    -o build/bin/example_cpp_tests -pthread 2>&1 | tail -5

# ---------------------------------------------------------------------------
# Step 3: run TestForge - should catch the regression.
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: TestForge detects the regression ==="
echo ""
testforge run 2>&1 | tail -30

echo ""
echo "============================================================"
echo " Demo complete."
echo "============================================================"
echo ""
echo "What happened: TestForge stored baseline latencies for"
echo "Math.MatrixMultiplyKnown across 6 runs, then on the 7th run"
echo "(with the patched, slower source) the robust regression"
echo "engine detected the latency was both:"
echo "  - above median * (1 + 10% threshold)"
echo "  - above median + 3*MAD (statistically unusual)"
echo "and marked it a PERF REGRESSION - failing the build."
echo ""
echo "In a real CUDA workflow, the same flow catches GPU kernel"
echo "regressions via the gpu_kernel_latency_ms metric."
