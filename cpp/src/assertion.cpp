// assertion.cpp
//
// Most of the assertion machinery is in the header (assertion.hpp) because
// the macros need to expand in user code. This .cpp exists only to keep
// the build system happy (a library with no .cpp files is awkward in CMake)
// and to host any non-macro helpers that don't fit elsewhere.

#include "testforge/assertion.hpp"

namespace testforge {
// Intentionally empty. See header comment.
}
