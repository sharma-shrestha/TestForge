// entry.cpp
//
// Implementation of testforge_main() - the reusable entry point for test
// binaries. Each test binary provides its own main() that delegates here.
// The test binary's TEST() registrations happen at static-init time
// before main() runs, so by the time testforge_main() is called the
// registry is fully populated.
//
// This means every test binary IS a worker. There is no separate
// "testforge_worker" binary with an empty registry - that was the
// architectural mistake in v0.3 and earlier.
//
// Output: a single JSON object on stdout (the RunReport). Stderr is for
// human-readable diagnostics and structured metric lines that the
// Python orchestrator parses (e.g. "test_name=Foo.Bar\ngpu_kernel_latency_ms=14.2").

#include "testforge/entry.hpp"
#include "testforge/json_writer.hpp"
#include "testforge/test_registry.hpp"
#include "testforge/test_runner.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace testforge {

static void usage(const char* progname) {
    std::cerr <<
        "usage: " << progname << " [--filter name1,name2,...] [--list] [--retries N]\n"
        "  --filter   comma-separated list of test names to run (default: all)\n"
        "  --list     print available test names and exit\n"
        "  --retries  default retry count for tests that don't override it\n";
}

static std::vector<std::string> split_csv(const std::string& s) {
    std::vector<std::string> out;
    std::stringstream ss(s);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (!item.empty()) out.push_back(item);
    }
    return out;
}

int testforge_main(int argc, char** argv) {
    std::vector<std::string> filter;
    bool list_only = false;
    int default_retries = 0;

    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--list") {
            list_only = true;
        } else if (a == "--filter" && i + 1 < argc) {
            filter = split_csv(argv[++i]);
        } else if (a == "--retries" && i + 1 < argc) {
            default_retries = std::atoi(argv[++i]);
        } else if (a == "--help" || a == "-h") {
            usage(argv[0]);
            return 0;
        } else {
            std::cerr << "unknown argument: " << a << "\n";
            usage(argv[0]);
            return 2;
        }
    }

    auto all = TestRegistry::instance().snapshot();

    if (list_only) {
        for (const auto& tc : all) {
            std::cout << tc.name << "\t" << tc.type << "\t" << tc.component << "\n";
        }
        return 0;
    }

    std::vector<TestCase> selected;
    if (filter.empty()) {
        selected = all;
    } else {
        for (const auto& name : filter) {
            auto tc = TestRegistry::instance().find(name);
            if (tc) selected.push_back(*tc);
            else std::cerr << "warning: no such test: " << name << "\n";
        }
    }

    RunOptions opts;
    opts.retries_default = default_retries;
    opts.on_start = [](const TestCase& tc) {
        // Emit a structured "test started" line so the orchestrator can
        // attach per-test GPU metrics to the right result by test_name,
        // not by index (the old approach was fragile).
        std::cerr << "test_name=" << tc.name << "\n";
        std::cerr << "[run] " << tc.name << " ...\n";
    };
    opts.on_finish = [](const TestCase& tc, const TestResult& r) {
        std::cerr << "       -> " << to_string(r.status)
                  << " (" << r.duration_ms << "ms, " << r.attempts << " attempt(s))\n";
        (void)tc;
    };

    TestRunner runner;
    auto results = runner.run_all(selected, opts);

    RunReport report;
    report.worker_id   = "worker-0";
    report.started_at  = std::chrono::system_clock::now() - std::chrono::milliseconds(1);
    report.finished_at = std::chrono::system_clock::now();
    report.results     = std::move(results);
    report.ok          = true;

    JsonWriter w(std::cout);
    w.write_report(report);
    std::cout << "\n";

    // Exit code: 0 if all passed, 1 if any failed/timed out.
    for (const auto& r : report.results) {
        if (r.status == TestStatus::Fail || r.status == TestStatus::Timeout) {
            return 1;
        }
    }
    return 0;
}

} // namespace testforge
