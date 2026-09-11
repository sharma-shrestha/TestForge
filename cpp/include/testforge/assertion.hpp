// testforge/assertion.hpp
//
// Assertion helpers. Two families:
//
//   ASSERT_*  - on failure, sets the failure state on the context and throws
//               to abort the test body. The test runner catches and marks
//               the test as failed.
//
//   EXPECT_*  - on failure, records the failure but lets the test body keep
//               running. Useful when you want to see all failures in one run
//               rather than just the first.
//
// Both families ALWAYS call ctx.record_assertion() so the result includes
// a complete assertion log. ASSERT_* additionally calls ctx.fail() and
// throws AssertionFailure to abort the test body.
//
// Implementation note: every assertion macro follows the same pattern:
//   1. evaluate the operands
//   2. record the assertion (passed or failed)
//   3. if failed: call ctx.fail() then throw
//
// This consistency matters because the assertion log is what makes failure
// clustering work - if some assertions skip record_assertion(), their
// failures are invisible to the clustering algorithm.

#pragma once

#include "testforge/test_case.hpp"

#include <cmath>
#include <sstream>
#include <stdexcept>
#include <string>

namespace testforge {

// Thrown by ASSERT_* on failure. Caught by TestRunner::run_one().
struct AssertionFailure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

namespace detail {

template <typename A, typename B>
std::string fail_msg(const char* a_expr, const char* b_expr,
                     const A& a, const B& b, const char* op) {
    std::ostringstream os;
    os << "expected " << a_expr << " " << op << " " << b_expr
       << ", got " << a << " " << op << " " << b;
    return os.str();
}

} // namespace detail
} // namespace testforge

// ---------------------------------------------------------------------------
// ASSERT_* macros
//
// Every ASSERT_* does:
//   1. record_assertion(condition, file, line, passed) - ALWAYS
//   2. if failed: ctx.fail(message, file, line) + throw AssertionFailure
//
// The record_assertion call is unconditional so the assertion log is
// complete regardless of pass/fail outcome.
// ---------------------------------------------------------------------------

#define ASSERT_EQ(a, b)                                                      \
    do {                                                                     \
        auto _va = (a); auto _vb = (b);                                      \
        if (!(_va == _vb)) {                                                 \
            std::string _m = testforge::detail::fail_msg(#a, #b, _va, _vb, "==");\
            ctx.record_assertion(#a " == " #b, __FILE__, __LINE__, false, _m);\
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#a " == " #b, __FILE__, __LINE__, true);       \
    } while (0)

#define ASSERT_NE(a, b)                                                      \
    do {                                                                     \
        auto _va = (a); auto _vb = (b);                                      \
        if (!(_va != _vb)) {                                                 \
            std::string _m = testforge::detail::fail_msg(#a, #b, _va, _vb, "!=");\
            ctx.record_assertion(#a " != " #b, __FILE__, __LINE__, false, _m);\
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#a " != " #b, __FILE__, __LINE__, true);       \
    } while (0)

#define ASSERT_TRUE(x)                                                       \
    do {                                                                     \
        if (!(x)) {                                                         \
            std::string _m = #x " is false";                                \
            ctx.record_assertion(#x, __FILE__, __LINE__, false, _m);        \
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#x, __FILE__, __LINE__, true);                  \
    } while (0)

#define ASSERT_FALSE(x)                                                      \
    do {                                                                     \
        if ((x)) {                                                           \
            std::string _m = #x " is true";                                 \
            ctx.record_assertion(#x, __FILE__, __LINE__, false, _m);        \
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#x, __FILE__, __LINE__, true);                  \
    } while (0)

#define ASSERT_NEAR(a, b, tol)                                               \
    do {                                                                     \
        auto _va = (a); auto _vb = (b); auto _t = (tol);                     \
        double _diff = std::fabs(static_cast<double>(_va) -                 \
                                 static_cast<double>(_vb));                  \
        if (_diff > static_cast<double>(_t)) {                              \
            std::ostringstream _os;                                          \
            _os << "expected |" #a " - " #b "| <= " << _t                    \
                << ", got " << _diff;                                       \
            std::string _m = _os.str();                                     \
            ctx.record_assertion(#a " ~= " #b, __FILE__, __LINE__, false, _m);\
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#a " ~= " #b, __FILE__, __LINE__, true);       \
    } while (0)

#define FAIL_MSG(msg)                                                        \
    do {                                                                     \
        std::string _m = msg;                                               \
        ctx.record_assertion("FAIL", __FILE__, __LINE__, false, _m);        \
        ctx.fail(_m, __FILE__, __LINE__);                                   \
        throw testforge::AssertionFailure(_m);                              \
    } while (0)

// ---------------------------------------------------------------------------
// EXPECT_* macros
//
// Same as ASSERT_* but does NOT throw - the test body continues. The
// failure is still recorded so it shows up in the result. Use this when
// you want to see all failures in one run, not just the first.
// ---------------------------------------------------------------------------

#define EXPECT_EQ(a, b)                                                      \
    do {                                                                     \
        auto _va = (a); auto _vb = (b);                                      \
        if (!(_va == _vb)) {                                                 \
            std::string _m = testforge::detail::fail_msg(#a, #b, _va, _vb, "==");\
            ctx.record_assertion(#a " == " #b, __FILE__, __LINE__, false, _m);\
            ctx.fail(_m, __FILE__, __LINE__);                                \
        } else {                                                             \
            ctx.record_assertion(#a " == " #b, __FILE__, __LINE__, true);    \
        }                                                                    \
    } while (0)

#define EXPECT_TRUE(x)                                                       \
    do {                                                                     \
        if (!(x)) {                                                         \
            std::string _m = #x " is false";                                \
            ctx.record_assertion(#x, __FILE__, __LINE__, false, _m);        \
            ctx.fail(_m, __FILE__, __LINE__);                                \
        } else {                                                             \
            ctx.record_assertion(#x, __FILE__, __LINE__, true);             \
        }                                                                    \
    } while (0)
