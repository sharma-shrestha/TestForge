// testforge/json_writer.hpp
//
// Tiny JSON serializer for TestResult / RunReport. We don't link a JSON
// library because the result schema is small and fixed, and a hand-rolled
// writer means the worker binary has zero third-party runtime deps (easier
// to ship in a container).

#pragma once

#include "testforge/test_result.hpp"

#include <ostream>
#include <string>

namespace testforge {

class JsonWriter {
public:
    explicit JsonWriter(std::ostream& out);

    void write_result(const TestResult& r);
    void write_report(const RunReport& r);

private:
    std::ostream& out_;
    void key(const std::string& k);
    void string(const std::string& s);
    void number(double d);
    void integer(long n);
    void boolean(bool b);
    void null();
};

} // namespace testforge
