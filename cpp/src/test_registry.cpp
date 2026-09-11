// test_registry.cpp

#include "testforge/test_registry.hpp"

#include <algorithm>

namespace testforge {

TestRegistry& TestRegistry::instance() {
    static TestRegistry r;
    return r;
}

int TestRegistry::register_test(const TestCase& tc) {
    std::lock_guard<std::mutex> lock(mu_);
    if (by_name_.count(tc.name)) {
        // Duplicate registration. This is almost always a copy-paste error
        // in a test file. We don't abort (the engine is still usable), but
        // we do log to stderr so the developer sees the collision.
        fprintf(stderr, "testforge: duplicate test registration for '%s'\n",
                tc.name.c_str());
        return static_cast<int>(by_name_[tc.name]);
    }
    by_name_[tc.name] = tests_.size();
    tests_.push_back(tc);
    return static_cast<int>(tests_.size() - 1);
}

std::vector<TestCase> TestRegistry::snapshot() const {
    std::lock_guard<std::mutex> lock(mu_);
    return tests_;
}

std::optional<TestCase> TestRegistry::find(const std::string& name) const {
    std::lock_guard<std::mutex> lock(mu_);
    auto it = by_name_.find(name);
    if (it == by_name_.end()) return std::nullopt;
    return tests_[it->second];
}

size_t TestRegistry::size() const {
    std::lock_guard<std::mutex> lock(mu_);
    return tests_.size();
}

// ----- TestBuilder -----

TestBuilder::TestBuilder(const char* file, int line, const char* suite, const char* name) {
    tc_.file   = file;
    tc_.line   = line;
    tc_.suite  = suite;
    tc_.name   = std::string(suite) + "." + std::string(name);
    tc_.type   = "cpu";
}

TestBuilder& TestBuilder::timeout(int ms)        { tc_.timeout_ms = ms; return *this; }
TestBuilder& TestBuilder::retries(int n)          { tc_.retries    = n; return *this; }
TestBuilder& TestBuilder::tag(const std::string& t)            { tc_.tags.push_back(t); return *this; }
TestBuilder& TestBuilder::component(const std::string& c)     { tc_.component = c; return *this; }
TestBuilder& TestBuilder::type(const std::string& t)          { tc_.type = t; return *this; }
TestBuilder& TestBuilder::depends_on(const std::string& c)    { tc_.depends_on.push_back(c); return *this; }

void TestBuilder::fn(TestFn body) {
    tc_.fn = std::move(body);
    TestRegistry::instance().register_test(tc_);
}

namespace detail {
void attach_meta(const std::string& suite, const std::string& name,
                 std::vector<std::string> /*kv_pairs*/) {
    // Currently a no-op; the TEST_META() macro is reserved for future
    // metadata that doesn't fit cleanly into the builder chain. We keep
    // the entry point so existing call sites don't break if we wire it up
    // later.
    (void)suite; (void)name;
}
}

} // namespace testforge
