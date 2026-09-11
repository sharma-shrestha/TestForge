"""Build helper - compiles the C++ engine + example test binaries without
requiring CMake. Useful when CMake isn't installed (e.g. minimal CI images).

Produces the same outputs as the CMake build:

    build/bin/example_cpp_tests

For CUDA builds, use CMake (the make-based build doesn't know about .cu).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

CORE_SOURCES = [
    "cpp/src/test_registry.cpp",
    "cpp/src/test_runner.cpp",
    "cpp/src/assertion.cpp",
    "cpp/src/test_result.cpp",
    "cpp/src/json_writer.cpp",
    "cpp/src/timeout.cpp",
    "cpp/src/entry.cpp",
]
EXAMPLE_MAIN = "cpp/examples/example_main.cpp"
CPU_TESTS = [
    "cpp/examples/cpu_tests.cpp",
    "cpp/examples/cpu_math_tests.cpp",
]
INCLUDE = "cpp/include"
OUTPUT  = "build/bin/example_cpp_tests"


def main() -> int:
    out_path = ROOT / OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        os.environ.get("CXX", "g++"),
        "-std=c++17",
        "-Wall", "-Wextra", "-Wpedantic",
        "-O2",
        f"-I{ROOT / INCLUDE}",
        *[str(ROOT / s) for s in (CORE_SOURCES + [EXAMPLE_MAIN] + CPU_TESTS)],
        "-o", str(out_path),
        "-pthread",
    ]
    print(" ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"build failed: g++ exited with {proc.returncode}", file=sys.stderr)
        return proc.returncode
    print(f"built: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
