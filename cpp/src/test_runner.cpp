// test_runner.cpp

#include "testforge/test_runner.hpp"
#include "testforge/assertion.hpp"
#include "testforge/timeout.hpp"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <exception>
#include <ratio>
#include <sys/resource.h>
#include <thread>

namespace testforge {

std::string to_string(TestStatus s) {
    switch (s) {
        case TestStatus::NotRun:  return "not_run";
        case TestStatus::Running: return "running";
        case TestStatus::Pass:    return "pass";
        case TestStatus::Fail:    return "fail";
        case TestStatus::Timeout:return "timeout";
        case TestStatus::Skipped: return "skipped";
        case TestStatus::Flaky:   return "flaky";
    }
    return "unknown";
}

// Capture resource usage of the current process for inclusion in the result.
// rusage covers user/sys CPU time and max RSS, which is enough for our
// purposes. GPU metrics are collected separately by the Python orchestrator
// (it can poll nvidia-smi while the worker runs).
static void capture_rusage(TestResult& r) {
    struct rusage ru;
    if (getrusage(RUSAGE_SELF, &ru) == 0) {
        r.peak_rss_kb = ru.ru_maxrss;       // kB on Linux, bytes on macOS - we
                                            // assume Linux for now; orchestrator
                                            // can normalize if needed.
        r.cpu_user_ms = static_cast<double>(ru.ru_utime.tv_sec)  * 1000.0
                       + static_cast<double>(ru.ru_utime.tv_usec) / 1000.0;
        r.cpu_sys_ms  = static_cast<double>(ru.ru_stime.tv_sec)  * 1000.0
                       + static_cast<double>(ru.ru_stime.tv_usec) / 1000.0;
    }
}

TestResult TestRunner::run_one(const TestCase& tc, const RunOptions& opts) const {
    TestResult r;
    r.test_name = tc.name;
    r.suite     = tc.suite;

    if (opts.on_start) opts.on_start(tc);

    int retries = (tc.retries > 0) ? tc.retries : opts.retries_default;
    int timeout_ms = (tc.timeout_ms > 0) ? tc.timeout_ms : opts.timeout_default_ms;

    for (int attempt = 1; attempt <= retries + 1; ++attempt) {
        r.attempts = attempt;

        TestContext ctx;
        ctx.reset();

        struct rusage before;
        getrusage(RUSAGE_SELF, &before);

        auto t0 = std::chrono::steady_clock::now();
        bool timed_out = false;

        try {
            timed_out = !run_with_timeout(
                std::chrono::milliseconds(timeout_ms),
                [&]() { tc.fn(ctx); });
        } catch (const AssertionFailure& e) {
            ctx.failed = true;
            ctx.failure_message = e.what();
        } catch (const std::exception& e) {
            ctx.failed = true;
            ctx.failure_message = std::string("uncaught exception: ") + e.what();
        } catch (...) {
            ctx.failed = true;
            ctx.failure_message = "unknown non-exception throwable";
        }

        auto t1 = std::chrono::steady_clock::now();
        r.duration_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

        capture_rusage(r);
        r.assertions = ctx.assertions;

        if (timed_out) {
            r.status = TestStatus::Timeout;
            r.failure_message = "timed out after " + std::to_string(timeout_ms) + "ms";
            // Don't retry a timeout - it's almost certainly an infinite loop
            // or deadlock, retrying just wastes time.
            break;
        }

        if (!ctx.failed) {
            // Passed. If we got here on a non-first attempt, the test is flaky.
            r.status = (attempt > 1) ? TestStatus::Flaky : TestStatus::Pass;
            r.failure_message.clear();
            break;
        }

        // Failed this attempt. Record details and either retry or give up.
        r.status           = TestStatus::Fail;
        r.failure_message  = ctx.failure_message;
        r.failure_file     = ctx.failure_file;
        r.failure_line     = ctx.failure_line;

        if (attempt <= retries) {
            continue;   // try again
        }
        break;          // no more retries, stay failed
    }

    // Build a stable error signature for clustering. The signature is
    // "file:line" if we have it (very stable across runs), otherwise
    // the failure message (which can drift).
    if (r.status == TestStatus::Fail || r.status == TestStatus::Timeout) {
        if (!r.failure_file.empty()) {
            r.error_signature = r.failure_file + ":" + std::to_string(r.failure_line);
        } else {
            r.error_signature = r.failure_message;
        }
    }

    if (opts.on_finish) opts.on_finish(tc, r);
    return r;
}

std::vector<TestResult> TestRunner::run_all(const std::vector<TestCase>& tests,
                                            const RunOptions& opts) const {
    std::vector<TestResult> out;
    out.reserve(tests.size());
    for (const auto& tc : tests) {
        auto r = run_one(tc, opts);
        out.push_back(std::move(r));
        if (opts.stop_on_failure && r.status == TestStatus::Fail) break;
    }
    return out;
}

} // namespace testforge
