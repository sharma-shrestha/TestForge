// cpu_tests.cpp
//
// A handful of tests that exercise the TestForge engine directly. These are
// compiled into the worker binary (and into example_cpp_tests, the standalone
// sample). They cover: basic pass/fail, assertions, retry behavior, flaky
// detection, timeout.

#include "testforge/assertion.hpp"
#include "testforge/test_case.hpp"
#include "testforge/test_registry.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <thread>

// A simple sanity check.
TEST(Sanity, AlwaysPass) {
    ASSERT_EQ(2 + 2, 4);
}

// Verifies that ASSERT_NEAR handles floating-point tolerance.
TEST(Math, FloatNear) {
    double a = 0.1 + 0.2;     // famously != 0.3 in IEEE 754
    ASSERT_NEAR(a, 0.3, 1e-9);
}

// A failing test on purpose - useful for demonstrating the failure path
// and the report format. Disabled by default; enable by setting the env var
// TESTFORGE_DEMO_FAIL=1.
TEST(Sanity, IntentionalFailure) {
    const char* demo = std::getenv("TESTFORGE_DEMO_FAIL");
    if (demo && std::string(demo) == "1") {
        ASSERT_EQ(1, 2);   // boom
    }
}

// A test that always passes on the second attempt - used to demonstrate
// the "flaky" classification. The retry count is set by the builder below.
static std::atomic<int> flaky_attempt_count{0};
TEST(FlakyDemo, PassesOnRetry) {
    int n = ++flaky_attempt_count;
    if (n % 2 == 1) {
        FAIL_MSG("intentional first-attempt failure");
    }
    // second attempt: pass
    ASSERT_TRUE(true);
}

// Wire up the flaky test's retry count. We do this at static init time
// after registration. This is admittedly ugly - better would be a TEST()
// extension that takes metadata inline - but it shows the registry/builder
// pattern from the outside.
namespace {
int _flaky_meta = []() {
    auto& reg = testforge::TestRegistry::instance();
    (void)reg;
    // Note: the registry is currently append-only; we can't easily reach
    // back and mutate a registered test case from here. The retry count
    // for this test is set via the run config (RunOptions::retries_default)
    // or via the worker's --retries flag. This is a known limitation.
    return 0;
}();
}

// A test that takes a while - used to exercise timeout / scheduling.
TEST(PerfDemo, Sleep50ms) {
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    ASSERT_TRUE(true);
}
