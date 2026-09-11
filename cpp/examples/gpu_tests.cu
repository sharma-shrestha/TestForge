// gpu_tests.cu
//
// Sample GPU tests. Each test:
//   1. builds input data on the host,
//   2. allocates device memory via DeviceBuffer<T> (RAII - freed on scope
//      exit even if an assertion throws),
//   3. launches a CUDA kernel,
//   4. copies the result back,
//   5. compares against a CPU reference implementation,
//   6. asserts near-equality within a tolerance.
//
// All CUDA API calls go through CHECK_CUDA(ctx, ...) so a CUDA error
// (allocation failure, memcpy failure, kernel launch failure) is recorded
// as a test failure with the full error string - not silently ignored.
//
// Kernel timing uses CudaEvent (RAII) and the latency is emitted to stderr
// as a structured line:
//   test_name=GPU.MatrixMultiply
//   gpu_kernel_latency_ms=14.2
//
// The Python orchestrator parses these lines and attaches the metric to
// the correct test result by test_name (not by index).

#include "testforge/assertion.hpp"
#include "testforge/cuda_helpers.hpp"
#include "testforge/test_case.hpp"
#include "testforge/test_registry.hpp"

#if TESTFORGE_HAVE_CUDA
#include <cuda_runtime.h>
extern "C" {
    void launch_vec_add(const float* a, const float* b, float* c, int n);
    void launch_matmul(const float* A, const float* B, float* C, int N);
    float launch_reduce(const float* in, int n);
}
#include <cmath>
#include <vector>
#endif

// ---------------------------------------------------------------------------
// GPU test: vector add
// ---------------------------------------------------------------------------
TEST(GPU, VectorAdd) {
#if TESTFORGE_HAVE_CUDA
    const int N = 1 << 16;
    std::vector<float> h_a(N), h_b(N), h_c(N);
    for (int i = 0; i < N; ++i) {
        h_a[i] = static_cast<float>(i) * 0.001f;
        h_b[i] = static_cast<float>(i) * 0.002f;
    }

    // RAII device buffers - freed automatically when they go out of scope,
    // even if an assertion throws below.
    DeviceBuffer<float> d_a(N), d_b(N), d_c(N);
    CHECK_CUDA(ctx, cudaMemcpy(d_a.get(), h_a.data(), N * sizeof(float),
                                cudaMemcpyHostToDevice));
    CHECK_CUDA(ctx, cudaMemcpy(d_b.get(), h_b.data(), N * sizeof(float),
                                cudaMemcpyHostToDevice));

    CudaEvent start, stop;
    CHECK_CUDA(ctx, cudaEventRecord(start.get()));
    launch_vec_add(d_a.get(), d_b.get(), d_c.get(), N);
    CHECK_CUDA(ctx, cudaEventRecord(stop.get()));
    CHECK_CUDA(ctx, cudaEventSynchronize(stop.get()));
    float ms = 0.0f;
    CHECK_CUDA(ctx, cudaEventElapsedTime(&ms, start.get(), stop.get()));

    CHECK_CUDA(ctx, cudaMemcpy(h_c.data(), d_c.get(), N * sizeof(float),
                                cudaMemcpyDeviceToHost));

    // Reference on CPU.
    int errors = 0;
    for (int i = 0; i < N; ++i) {
        float expected = h_a[i] + h_b[i];
        if (std::fabs(h_c[i] - expected) > 1e-5f) {
            if (errors < 5) {
                std::cerr << "mismatch at " << i << ": got " << h_c[i]
                          << " expected " << expected << "\n";
            }
            ++errors;
        }
    }
    ASSERT_EQ(errors, 0);

    // Emit structured metric line for the orchestrator to parse.
    std::cerr << "gpu_kernel_latency_ms=" << ms << "\n";
#else
    FAIL_MSG("compiled without CUDA support; rebuild with -DTESTFORGE_ENABLE_CUDA=ON");
#endif
}

// ---------------------------------------------------------------------------
// GPU test: matrix multiply
// ---------------------------------------------------------------------------
TEST(GPU, MatrixMultiply) {
#if TESTFORGE_HAVE_CUDA
    const int N = 256;
    std::vector<float> h_A(N * N), h_B(N * N), h_C(N * N, 0.0f);
    for (int i = 0; i < N * N; ++i) {
        h_A[i] = static_cast<float>(i % 17) * 0.01f;
        h_B[i] = static_cast<float>((i * 3) % 23) * 0.01f;
    }

    DeviceBuffer<float> d_A(N * N), d_B(N * N), d_C(N * N);
    CHECK_CUDA(ctx, cudaMemcpy(d_A.get(), h_A.data(), N * N * sizeof(float),
                                cudaMemcpyHostToDevice));
    CHECK_CUDA(ctx, cudaMemcpy(d_B.get(), h_B.data(), N * N * sizeof(float),
                                cudaMemcpyHostToDevice));

    CudaEvent start, stop;
    CHECK_CUDA(ctx, cudaEventRecord(start.get()));
    launch_matmul(d_A.get(), d_B.get(), d_C.get(), N);
    CHECK_CUDA(ctx, cudaEventRecord(stop.get()));
    CHECK_CUDA(ctx, cudaEventSynchronize(stop.get()));
    float ms = 0.0f;
    CHECK_CUDA(ctx, cudaEventElapsedTime(&ms, start.get(), stop.get()));

    CHECK_CUDA(ctx, cudaMemcpy(h_C.data(), d_C.get(), N * N * sizeof(float),
                                cudaMemcpyDeviceToHost));

    // Reference.
    int errors = 0;
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            float s = 0.0f;
            for (int k = 0; k < N; ++k) {
                s += h_A[i * N + k] * h_B[k * N + j];
            }
            if (std::fabs(h_C[i * N + j] - s) > 1e-3f) {
                if (errors < 5) {
                    std::cerr << "mismatch at (" << i << "," << j
                              << "): got " << h_C[i * N + j]
                              << " expected " << s << "\n";
                }
                ++errors;
            }
        }
    }
    ASSERT_EQ(errors, 0);

    std::cerr << "gpu_kernel_latency_ms=" << ms << "\n";
#else
    FAIL_MSG("compiled without CUDA support");
#endif
}

// ---------------------------------------------------------------------------
// GPU test: memory stress
//
// Repeatedly allocates and frees a large buffer using RAII. The point of
// this test is to catch allocator leaks or fragmentation - if cudaMalloc
// starts failing after N iterations, something is wrong.
// ---------------------------------------------------------------------------
TEST(GPU, MemoryStress) {
#if TESTFORGE_HAVE_CUDA
    const int iters = 50;
    const size_t bytes = 256ULL * 1024 * 1024;  // 256 MB
    int failures = 0;
    for (int i = 0; i < iters; ++i) {
        try {
            DeviceBuffer<char> buf(bytes);
            // Buffer is freed here when buf goes out of scope.
        } catch (const std::runtime_error& e) {
            ++failures;
            std::cerr << "iteration " << i << ": " << e.what() << "\n";
        }
    }
    ASSERT_EQ(failures, 0);
#else
    FAIL_MSG("compiled without CUDA support");
#endif
}
