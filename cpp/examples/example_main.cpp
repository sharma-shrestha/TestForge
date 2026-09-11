// example_main.cpp
//
// Shared main() for example test binaries. Each test binary (example_cpp_tests,
// example_gpu_tests) links this file alongside its test source files. The
// TEST() registrations in those files happen at static-init time, then
// main() calls testforge_main() which runs the registered tests and writes
// a JSON report to stdout.
//
// This file is intentionally tiny - it exists only to provide the main()
// symbol. The real logic lives in testforge_main() (in entry.cpp, linked
// via libtestforge_core).

#include "testforge/entry.hpp"

int main(int argc, char** argv) {
    return testforge::testforge_main(argc, argv);
}
