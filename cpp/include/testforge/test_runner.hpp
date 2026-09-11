// testforge/test_runner.hpp
//
// Runs registered tests, collects results. The runner is the only place
// that decides pass/fail/timeout status - the test body itself just records
// assertions and may throw AssertionFailure, but the runner is what
// materializes that into a TestResult.

#pragma once

#include "testforge/test_case.hpp"
#include "testforge/test_result.hpp"

#include <functional>
#include <string>
#include <vector>

namespace testforge {

struct RunOptions {
    int  timeout_default_ms = 30000;
    int  retries_default    = 0;
    bool stop_on_failure    = false;
    // Called once per test as it starts. Useful for progress reporting
    // from the worker.
    std::function<void(const TestCase&)> on_start = nullptr;
    // Called once per test (per attempt) when it finishes.
    std::function<void(const TestCase&, const TestResult&)> on_finish = nullptr;
};

class TestRunner {
public:
    // Runs a single test, applying timeout and retries. The result reflects
    // the *final* status after retries (e.g. a test that fails twice and
    // passes on the third attempt gets status=Flaky with attempts=3).
    TestResult run_one(const TestCase& tc, const RunOptions& opts) const;

    // Runs a batch of tests sequentially. Results are returned in the same
    // order as the input.
    std::vector<TestResult> run_all(const std::vector<TestCase>& tests,
                                    const RunOptions& opts) const;
};

} // namespace testforge
