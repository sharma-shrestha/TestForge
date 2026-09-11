// testforge/entry.hpp
//
// Reusable entry point for test binaries. Each test binary (e.g.
// example_cpp_tests, example_gpu_tests) links testforge_core and provides
// its own main() that delegates to testforge_main(). This means every test
// binary IS a worker - there is no separate "testforge_worker" binary
// with an empty registry.
//
// Usage in a test binary:
//
//     #include "testforge/entry.hpp"
//     int main(int argc, char** argv) {
//         return testforge_main(argc, argv);
//     }
//
// The test binary's TEST() registrations happen at static-init time
// before main() runs, so by the time testforge_main() is called the
// registry is fully populated.

#pragma once

namespace testforge {

// Process command-line arguments, run the requested tests, write a JSON
// report to stdout, return an exit code (0 = all passed, 1 = at least
// one failure, 2 = usage error).
int testforge_main(int argc, char** argv);

} // namespace testforge
