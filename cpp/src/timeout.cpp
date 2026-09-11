// timeout.cpp

#include "testforge/timeout.hpp"

#include <chrono>
#include <future>
#include <thread>

namespace testforge {

bool run_with_timeout(std::chrono::milliseconds timeout,
                      const std::function<void()>& body) {
    std::packaged_task<void()> task(body);
    std::future<void> fut = task.get_future();
    std::thread worker(std::move(task));
    worker.detach();

    auto status = fut.wait_for(timeout);
    if (status == std::future_status::timeout) {
        // The thread is still running. We can't cancel it (std::thread has
        // no cancel()), so we detach and let it die when the process exits.
        // The test is marked Timeout regardless. In a forked model the
        // orchestrator would kill the child; here we rely on the worker
        // process being short-lived.
        return false;
    }
    // Either ready or deferred. If ready and the body threw, .get() rethrows.
    // We swallow the exception - the caller (TestRunner::run_one) wraps body
    // in its own try/catch that records the failure properly, so by the time
    // we get here the exception has already been turned into a ctx.fail().
    try { fut.get(); } catch (...) { /* already recorded */ }
    return true;
}

} // namespace testforge
