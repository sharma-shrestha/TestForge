# Contributing to TestForge

This is a personal project. These notes are mostly for future-me.

## Code style

**C++**: C++17, no extensions. `-Wall -Wextra -Wpedantic -Wshadow`.
Header guards via `#pragma once`. Snake_case for everything except
class/struct names (PascalCase) and macro names (UPPER_SNAKE).

**Python**: 4-space indent, type hints on public functions, dataclasses
over dicts where the shape is fixed. No external formatter config -
follow what's already in the file.

## Layout

```
cpp/include/testforge/   # public headers (consumed by tests)
cpp/src/                  # engine implementation
cpp/examples/             # sample tests (CPU + CUDA)
python/testforge/         # orchestration library
python/cli/               # CLI entry point
tests/                    # pytest tests for the Python layer
db/                       # SQL schema (kept in sync with storage.py)
docs/                     # architecture + design notes
examples/demo/            # the killer demo
```

## Adding a new test type

TestForge currently supports three kinds: `cpp_engine`, `pytest`,
`binary`. To add a fourth:

1. Add a new `kind` value to `TestSpec` in `discovery.py`.
2. Add a `_run_<kind>_job` function in `scheduler.py` that takes a
   `WorkerJob` and returns a `list[dict]` of result objects (same
   shape as the worker's JSON output).
3. Add a discovery function that finds tests of this kind.
4. Add tests in `tests/` for the new kind.

## Adding a new metric

1. Extend the `TestResult` struct in `test_result.hpp`.
2. Update `JsonWriter::write_result` to emit the new field.
3. Extend `StoredResult` in `storage.py` and add a column to the schema
   in both `SCHEMA_SQLITE` and `SCHEMA_PG`.
4. If it's a regression-tracked metric, add it to `regression.py`'s
   `_check_metric` calls and add a threshold to `RegressionThresholds`.
5. Update the reporter to display it.

## Running tests

```bash
# Build and run the C++ engine directly
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/bin/testforge_worker

# Python unit tests
cd python && pytest ../tests/python/

# End-to-end smoke
testforge init
testforge discover
testforge run --html /tmp/report.html
```

## Cutting a release

1. Update `version` in `pyproject.toml` and the CMakeLists `project()`
   call to match.
2. Update `CHANGELOG.md` with what changed since the last version.
3. Tag: `git tag v0.X.0 && git push --tags`.
4. The GitHub Actions workflow builds and tests on tag push.

## Known rough edges

- The C++ engine's `TestBuilder` doesn't expose a clean way to set
  per-test metadata from the test body. Currently you set it via
  `RunOptions::retries_default` at the runner level, which is too
  coarse. Fix: add a `Meta()` macro that runs at static init time
  after registration to mutate the registered test case.
- The pytest discovery path is naive (parses `pytest --co` output). It
  doesn't handle parametrized tests well - each parametrization shows
  up as a separate spec, which is fine, but the `name` field gets
  ugly with `[param1]` suffixes.
- Distributed workers are documented but not implemented. See
  `docs/distributed_workers.md`.
- The LLM analyst currently sends the full failure message + similar
  history to the LLM endpoint. For very long stack traces this could
  exceed token limits; we should truncate at ~2k tokens.
