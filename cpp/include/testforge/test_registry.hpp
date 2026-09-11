// testforge/test_registry.hpp
//
// Global registry of test cases. Tests register themselves at static-init
// time via the TEST() macro. The registry is a Meyers singleton so we don't
// have to worry about init order across translation units - the first call
// to TestRegistry::instance() constructs it.
//
// This is intentionally thread-unsafe for registration (registration happens
// before main()), but the snapshot used by TestRunner is taken once and then
// immutable.

#pragma once

#include "testforge/test_case.hpp"

#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace testforge {

class TestRegistry {
public:
    static TestRegistry& instance();

    // Register a test. Returns a handle that can be used to chain metadata
    // (timeout, retries, tags) onto the registration via builder-style calls
    // from the TEST() macro expansion.
    int register_test(const TestCase& tc);

    // Returns a snapshot of all registered tests. Subsequent registrations
    // (which shouldn't happen after main() starts, but be safe) are not
    // reflected in the returned vector.
    std::vector<TestCase> snapshot() const;

    // Lookup by name; returns std::nullopt if not found.
    //
    // Returns a *copy* of the TestCase, not a pointer. The underlying vector
    // can be reallocated by future registrations, so returning a pointer
    // would risk dangling. A copy is cheap (TestCase is a few hundred bytes
    // of strings) and is always safe.
    std::optional<TestCase> find(const std::string& name) const;

    size_t size() const;

private:
    TestRegistry() = default;
    mutable std::mutex              mu_;
    std::vector<TestCase>           tests_;
    std::unordered_map<std::string, size_t> by_name_;
};

// Builder used by the TEST() macro to attach metadata. Each method returns
// *this so calls can chain:
//
//   testforge::detail::TestBuilder(__FILE__, __LINE__, "Suite", "Name")
//       .timeout(5000)
//       .retries(2)
//       .tag("gpu")
//       .depends_on("memory")
//       .fn([](testforge::TestContext& ctx) { ... });
//
class TestBuilder {
public:
    TestBuilder(const char* file, int line, const char* suite, const char* name);

    TestBuilder& timeout(int ms);
    TestBuilder& retries(int n);
    TestBuilder& tag(const std::string& t);
    TestBuilder& component(const std::string& c);
    TestBuilder& type(const std::string& t);
    TestBuilder& depends_on(const std::string& component);

    // The final call that captures the test body and registers it.
    void fn(TestFn body);

private:
    TestCase tc_;
};

} // namespace testforge

// ---------------------------------------------------------------------------
// TEST() macro family
//
// Usage:
//   TEST(MatrixMul, BasicCorrectness) {
//       ASSERT_NEAR(...);
//   }
//
// Expands to a TestBuilder that registers a test whose body is a lambda
// capturing the assertion context. The lambda takes a TestContext& named
// `ctx` so user code can write ASSERT_EQ(a, b) which expands to
//   testforge::detail::check_eq(ctx, #a, #b, a, b, __FILE__, __LINE__);
//
#define TEST(suite, name)                                                     \
    static void testforge_test_##suite##_##name(testforge::TestContext& ctx); \
    static int testforge_reg_##suite##_##name = []() {                        \
        testforge::TestBuilder b(__FILE__, __LINE__, #suite, #name);          \
        b.fn(testforge_test_##suite##_##name);                                \
        return 0;                                                             \
    }();                                                                      \
    static void testforge_test_##suite##_##name(testforge::TestContext& ctx)

// Tag a test. Must appear before the body. Used as:
//   TEST(Foo, Bar) { ... }
//   TEST_TAG(Foo, Bar, "gpu").timeout(5000);
// We instead expose metadata via the TEST_META() macro for clarity.
#define TEST_META(suite, name, ...)                                           \
    static int testforge_meta_##suite##_##name = []() {                       \
        testforge::detail::attach_meta(#suite, #name, {__VA_ARGS__});          \
        return 0;                                                             \
    }();
