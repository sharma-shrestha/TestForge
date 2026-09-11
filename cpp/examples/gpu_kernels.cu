// gpu_kernels.cu
//
// CUDA kernels used by gpu_tests.cu. Kept in a separate translation unit so
// that:
//   - the kernels can be compiled with nvcc and linked into the test binary
//     without polluting the C++ test file with .cu syntax;
//   - the kernels can be reused (e.g. by a benchmark harness) without pulling
//     in the test framework.
//
// The implementations here are deliberately naive. They are not meant to
// be fast - they are meant to be obviously correct, so that they can serve
// as a reference for the optimized kernel and as a workload for TestForge
// to validate against.

#include <cuda_runtime.h>
#include <vector>

// ----- vector add: c = a + b -----
__global__ void vec_add_kernel(const float* a, const float* b, float* c, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) c[i] = a[i] + b[i];
}

extern "C" void launch_vec_add(const float* a, const float* b, float* c, int n) {
    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    vec_add_kernel<<<blocks, threads>>>(a, b, c, n);
    cudaDeviceSynchronize();
}

// ----- matrix multiply: C = A * B, N x N -----
__global__ void matmul_kernel(const float* A, const float* B, float* C, int N) {
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;
    if (row < N && col < N) {
        float s = 0.0f;
        for (int k = 0; k < N; ++k) {
            s += A[row * N + k] * B[k * N + col];
        }
        C[row * N + col] = s;
    }
}

extern "C" void launch_matmul(const float* A, const float* B, float* C, int N) {
    dim3 threads(16, 16);
    dim3 blocks((N + 15) / 16, (N + 15) / 16);
    matmul_kernel<<<blocks, threads>>>(A, B, C, N);
    cudaDeviceSynchronize();
}

// ----- reduction: sum of array -----
__global__ void reduce_kernel(const float* in, float* out, int n) {
    __shared__ float sdata[256];
    int tid = threadIdx.x;
    int i = blockIdx.x * blockDim.x + tid;
    sdata[tid] = (i < n) ? in[i] : 0.0f;
    __syncthreads();
    for (int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (tid < s) sdata[tid] += sdata[tid + s];
        __syncthreads();
    }
    if (tid == 0) out[blockIdx.x] = sdata[0];
}

extern "C" float launch_reduce(const float* in, int n) {
    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    float* d_partial = nullptr;
    float* d_in = nullptr;
    cudaMalloc(&d_in, n * sizeof(float));
    cudaMemcpy(d_in, in, n * sizeof(float), cudaMemcpyHostToDevice);
    cudaMalloc(&d_partial, blocks * sizeof(float));
    reduce_kernel<<<blocks, threads>>>(d_in, d_partial, n);
    std::vector<float> h_partial(blocks);
    cudaMemcpy(h_partial.data(), d_partial, blocks * sizeof(float),
               cudaMemcpyDeviceToHost);
    float s = 0.0f;
    for (float v : h_partial) s += v;
    cudaFree(d_in);
    cudaFree(d_partial);
    return s;
}
