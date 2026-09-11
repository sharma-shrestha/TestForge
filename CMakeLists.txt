cmake_minimum_required(VERSION 3.16)
project(testforge
    VERSION 0.5.0
    DESCRIPTION "Distributed test automation & GPU validation framework"
    LANGUAGES CXX)

# ---------------------------------------------------------------------------
# Build options
# ---------------------------------------------------------------------------
option(TESTFORGE_BUILD_EXAMPLES "Build example test binaries" ON)
option(TESTFORGE_ENABLE_CUDA    "Enable CUDA test support (requires CUDA toolkit)" OFF)

# ---------------------------------------------------------------------------
# Compiler setup
# ---------------------------------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_compile_options(
    -Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor
    -Wno-unused-parameter
)

# ---------------------------------------------------------------------------
# CUDA setup (optional)
#
# Architectures are configurable via -DCMAKE_CUDA_ARCHITECTURES=... on the
# cmake command line, or via the TESTFORGE_CUDA_ARCHITECTURES env var. If
# neither is set, we use "native" which lets CMake auto-detect the current
# GPU. This is much less brittle than hardcoding a list that drifts as
# new GPU generations ship.
# ---------------------------------------------------------------------------
if(TESTFORGE_ENABLE_CUDA)
    enable_language(CUDA)
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
        if(DEFINED ENV{TESTFORGE_CUDA_ARCHITECTURES})
            set(CMAKE_CUDA_ARCHITECTURES "$ENV{TESTFORGE_CUDA_ARCHITECTURES}")
        else()
            # "native" tells CMake to detect the GPU(s) on the build machine.
            # Override with -DCMAKE_CUDA_ARCHITECTURES="75;80;86" if you need
            # to target a specific set of architectures (e.g. for CI).
            set(CMAKE_CUDA_ARCHITECTURES "native")
        endif()
    endif()
    add_compile_definitions(TESTFORGE_HAVE_CUDA=1)
else()
    add_compile_definitions(TESTFORGE_HAVE_CUDA=0)
endif()

# ---------------------------------------------------------------------------
# Core engine library
#
# libtestforge_core contains the test engine AND the reusable entry point
# (testforge_main). Test binaries link this library and provide their own
# main() that delegates to testforge_main(). This means every test binary
# IS a worker - there is no separate "testforge_worker" binary.
# ---------------------------------------------------------------------------
add_library(testforge_core STATIC
    cpp/src/test_registry.cpp
    cpp/src/test_runner.cpp
    cpp/src/assertion.cpp
    cpp/src/test_result.cpp
    cpp/src/json_writer.cpp
    cpp/src/timeout.cpp
    cpp/src/entry.cpp
)
target_include_directories(testforge_core PUBLIC cpp/include)
target_compile_features(testforge_core PUBLIC cxx_std_17)
find_package(Threads REQUIRED)
target_link_libraries(testforge_core PUBLIC Threads::Threads)

# ---------------------------------------------------------------------------
# Example test binaries
#
# Each test binary links testforge_core + example_main.cpp (which provides
# main()). The test source files (cpu_tests.cpp, gpu_tests.cu, etc.) contain
# TEST() registrations that fire at static-init time.
# ---------------------------------------------------------------------------
if(TESTFORGE_BUILD_EXAMPLES)
    # CPU example: exercises the TestForge engine directly
    add_executable(example_cpp_tests
        cpp/examples/example_main.cpp
        cpp/examples/cpu_tests.cpp
        cpp/examples/cpu_math_tests.cpp
    )
    target_link_libraries(example_cpp_tests PRIVATE testforge_core)
    set_target_properties(example_cpp_tests PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")

    # GPU example: requires CUDA toolkit. Built only when -DTESTFORGE_ENABLE_CUDA=ON.
    if(TESTFORGE_ENABLE_CUDA)
        add_executable(example_gpu_tests
            cpp/examples/example_main.cpp
            cpp/examples/gpu_tests.cu
            cpp/examples/gpu_kernels.cu
        )
        target_link_libraries(example_gpu_tests PRIVATE testforge_core)
        set_target_properties(example_gpu_tests PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    endif()
endif()

# ---------------------------------------------------------------------------
# Install rules (optional, useful when packaged)
# ---------------------------------------------------------------------------
include(GNUInstallDirs)
install(TARGETS testforge_core
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY cpp/include/testforge
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
