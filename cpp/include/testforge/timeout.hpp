// testforge/timeout.hpp
//
// Watchdog-based timeout for test execution. We spawn the test body on a
// worker thread and join it with a timeout; if the join times out, we
// detach the thread (it'll be killed when the process exits) and report
// TestStatus::Timeout.
//
// Detaching is ugly but unavoidable: C++ std::thread has no cancel(). In
// a production-grade runner we'd fork() the test and kill the child on
// timeout, which is exactly what the Python orchestrator does for test
// binaries it spawns. Inside the C++ engine, we use the thread-based
// approach for tests registered directly with the engine.

#pragma once

#include <chrono>
#include <functional>
#include <thread>

namespace testforge {

// Runs `body` and returns true if it finished within `timeout_ms`.
// Returns false if the body is still running (in which case the underlying
// thread is detached - caller should treat the result as garbage).
bool run_with_timeout(std::chrono::milliseconds timeout,
                      const std::function<void()>& body);

} // namespace testforge
