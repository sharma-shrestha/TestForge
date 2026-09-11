// cpu_math_tests.cpp
//
// Tests for a small CPU math library (matrix multiply, dot product, reduction).
// These mirror the GPU tests in gpu_tests.cu so the same workload can be
// compared CPU-vs-GPU for correctness and performance - that's the core of
// GPU validation work.

#include "testforge/assertion.hpp"
#include "testforge/test_case.hpp"
#include "testforge/test_registry.hpp"

#include <cmath>
#include <vector>

// Naive row-major matrix multiply: C = A * B, all N x N.
static std::vector<float> matmul(const std::vector<float>& A,
                                 const std::vector<float>& B, int N) {
    std::vector<float> C(N * N, 0.0f);
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            float s = 0.0f;
            for (int k = 0; k < N; ++k) {
                s += A[i * N + k] * B[k * N + j];
            }
            C[i * N + j] = s;
        }
    }
    return C;
}

TEST(Math, MatrixMultiplyIdentity) {
    const int N = 8;
    std::vector<float> A(N * N), B(N * N), expected(N * N);
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            A[i * N + j] = static_cast<float>(i * N + j);
            B[i * N + j] = (i == j) ? 1.0f : 0.0f;
        }
    }
    auto C = matmul(A, B, N);
    for (int i = 0; i < N * N; ++i) {
        ASSERT_NEAR(C[i], A[i], 1e-5f);
    }
}

TEST(Math, MatrixMultiplyKnown) {
    // 2x2: [[1,2],[3,4]] * [[5,6],[7,8]] = [[19,22],[43,50]]
    std::vector<float> A = {1, 2, 3, 4};
    std::vector<float> B = {5, 6, 7, 8};
    auto C = matmul(A, B, 2);
    ASSERT_NEAR(C[0], 19.0f, 1e-5f);
    ASSERT_NEAR(C[1], 22.0f, 1e-5f);
    ASSERT_NEAR(C[2], 43.0f, 1e-5f);
    ASSERT_NEAR(C[3], 50.0f, 1e-5f);
}

TEST(Math, DotProduct) {
    std::vector<float> a = {1, 2, 3, 4};
    std::vector<float> b = {5, 6, 7, 8};
    float s = 0;
    for (size_t i = 0; i < a.size(); ++i) s += a[i] * b[i];
    ASSERT_NEAR(s, 70.0f, 1e-5f);
}

TEST(Math, Reduction) {
    std::vector<float> xs(1000);
    for (size_t i = 0; i < xs.size(); ++i) xs[i] = static_cast<float>(i);
    float s = 0;
    for (auto v : xs) s += v;
    ASSERT_NEAR(s, 499500.0f, 1e-3f);
}
