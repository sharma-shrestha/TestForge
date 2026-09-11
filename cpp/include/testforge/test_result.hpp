// testforge/test_result.hpp
//
// Result of running one test (one logical execution, possibly with retries).
// Serialized to JSON by json_writer for inter-process transport - the
// worker writes results to stdout, the Python orchestrator parses them.

#pragma once

#include "testforge/test_case.hpp"

#include <chrono>
#include <string>
#include <vector>

namespace testforge {

struct TestResult {
    std::string  test_name;
    std::string  suite;
    TestStatus   status        = TestStatus::NotRun;
    int          attempts      = 0;          // 1 = first try, 2 = retry once, etc.
    double       duration_ms   = 0.0;
    std::string  failure_message;
    std::string  failure_file;
    int          failure_line  = 0;
    std::string  stack_trace;                 // captured if available
    std::vector<AssertionRecord> assertions;

    // Resource metrics, filled in by the worker process via getrusage / psutil.
    // -1 or empty string means "not measured".
    long         peak_rss_kb        = -1;
    double       cpu_user_ms        = -1.0;
    double       cpu_sys_ms          = -1.0;

    // GPU metrics, populated when available.
    double       gpu_utilization_pct = -1.0;
    long         gpu_memory_used_mb  = -1;
    double       gpu_kernel_latency_ms = -1.0;
    std::string  gpu_device_name;            // empty when no GPU

    // Stable signature for clustering. The worker computes this from
    // failure_message + (normalized) stack_trace so the same bug across
    // builds lands in the same cluster.
    std::string  error_signature;
};

// A serializable bundle of all results from one worker invocation.
struct RunReport {
    std::string              worker_id;
    std::chrono::system_clock::time_point started_at;
    std::chrono::system_clock::time_point finished_at;
    std::vector<TestResult>  results;
    bool                     ok = true;
    std::string              error;
};

} // namespace testforge
