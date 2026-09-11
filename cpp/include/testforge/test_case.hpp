// testforge/test_case.hpp
//
// The core unit of testing. A TestCase is a name + a function pointer + a
// TestContext. The function pointer is invoked by TestRunner inside a
// watchdog thread; failures bubble up via exceptions that the runner catches.
//
// Why a struct and not a class with private members? Because tests are
// registered at static-init time via the TEST() macro, and that macro needs
// to be able to construct a TestCase without friend declarations in every
// translation unit. Keep it a POD-ish struct.

#pragma once

#include <chrono>
#include <functional>
#include <string>
#include <vector>

namespace testforge {

enum class TestStatus {
    NotRun,
    Running,
    Pass,
    Fail,
    Timeout,
    Skipped,
    Flaky,        // passed after retry
};

std::string to_string(TestStatus s);

struct AssertionRecord {
    std::string condition;
    std::string file;
    int         line;
    bool        passed;
    std::string message;   // optional, may be empty
};

struct TestContext {
    std::vector<AssertionRecord> assertions;
    bool                         failed = false;
    std::string                  failure_message;
    std::string                  failure_file;
    int                          failure_line = 0;

    void reset() {
        assertions.clear();
        failed = false;
        failure_message.clear();
        failure_file.clear();
        failure_line = 0;
    }

    void record_assertion(const std::string& cond, const std::string& file,
                          int line, bool passed, const std::string& msg = "") {
        assertions.push_back({cond, file, line, passed, msg});
    }

    void fail(const std::string& msg, const std::string& file, int line) {
        failed = true;
        failure_message = msg;
        failure_file    = file;
        failure_line    = line;
    }
};

using TestFn = std::function<void(TestContext&)>;

struct TestCase {
    std::string  name;
    std::string  suite;
    std::string  component;     // e.g. "memory", "matrix_engine"
    std::string  type;          // "cpu" | "gpu" | "integration"
    std::string  file;
    int          line           = 0;
    int          timeout_ms     = 30000;   // 30s default
    int          retries        = 0;
    TestFn       fn;
    std::vector<std::string> tags;
    std::vector<std::string> depends_on;   // names of components this test depends on
};

} // namespace testforge
