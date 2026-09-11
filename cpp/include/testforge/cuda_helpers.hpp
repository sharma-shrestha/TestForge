// testforge/cuda_helpers.hpp
//
// RAII wrappers and error-checking macros for CUDA. These are the single
// place where CUDA resource management happens - test code uses these
// wrappers instead of raw cudaMalloc/cudaFree/etc. so cleanup is automatic
// even when an assertion throws.
//
// Why this matters: before v0.5, the GPU tests called cudaMalloc directly
// and cudaFree at the end of the test body. If an ASSERT_* threw before
// the cudaFree, the GPU memory leaked. With RAII, the destructor runs
// during stack unwinding, so the memory is freed even on exception.
//
// These wrappers are only available when TESTFORGE_HAVE_CUDA=1. When CUDA
// is not enabled, the types still exist (as empty stubs) so test code
// compiles - but using them without CUDA is a compile error.

#pragma once

#if TESTFORGE_HAVE_CUDA
#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace testforge {

// ---------------------------------------------------------------------------
// CHECK_CUDA - the only way to call a CUDA API function in test code.
//
// If the CUDA call returns anything other than cudaSuccess, this records
// a failure on the test context and throws AssertionFailure so the test
// body aborts. The failure message includes the CUDA error code, the
// human-readable error string, the operation name, the source file, and
// the line - which gives the failure analyst enough to reason about
// "cudaErrorMemoryAllocation" rather than a vague "something failed".
//
// Usage:
//   CHECK_CUDA(ctx, cudaMalloc(&d_a, n * sizeof(float)));
//
#define CHECK_CUDA(ctx, call)                                                 \
    do {                                                                     \
        cudaError_t _err = (call);                                           \
        if (_err != cudaSuccess) {                                           \
            std::string _m = std::string("CUDA error: ")                      \
                + cudaGetErrorString(_err)                                    \
                + " (code " + std::to_string(_err) + ")"                     \
                + " in " #call;                                              \
            ctx.record_assertion(#call, __FILE__, __LINE__, false, _m);     \
            ctx.fail(_m, __FILE__, __LINE__);                                \
            throw testforge::AssertionFailure(_m);                           \
        }                                                                    \
        ctx.record_assertion(#call, __FILE__, __LINE__, true);              \
    } while (0)

// ---------------------------------------------------------------------------
// RAII wrapper for device memory.
//
// Allocates in the constructor, frees in the destructor. Copy is disabled
// (would lead to double-free); move is allowed.
//
// Usage:
//   DeviceBuffer<float> d_a(ctx, N);  // allocates N floats on device
//   CHECK_CUDA(ctx, cudaMemcpy(d_a.get(), h_a.data(), N * sizeof(float),
//                              cudaMemcpyHostToDevice));
//
template <typename T>
class DeviceBuffer {
public:
    DeviceBuffer() : ptr_(nullptr), count_(0) {}

    // Allocates count * sizeof(T) bytes on the device. Throws on failure
    // (caller should wrap construction in try/catch or use the two-phase
    // init pattern: default-construct, then alloc()).
    explicit DeviceBuffer(size_t count) : ptr_(nullptr), count_(count) {
        cudaError_t err = cudaMalloc(&ptr_, count * sizeof(T));
        if (err != cudaSuccess) {
            ptr_ = nullptr;
            count_ = 0;
            throw std::runtime_error(std::string("cudaMalloc failed: ")
                                     + cudaGetErrorString(err));
        }
    }

    ~DeviceBuffer() {
        if (ptr_) {
            cudaFree(ptr_);
            ptr_ = nullptr;
        }
    }

    // Movable, not copyable.
    DeviceBuffer(DeviceBuffer&& o) noexcept : ptr_(o.ptr_), count_(o.count_) {
        o.ptr_ = nullptr;
        o.count_ = 0;
    }
    DeviceBuffer& operator=(DeviceBuffer&& o) noexcept {
        if (this != &o) {
            if (ptr_) cudaFree(ptr_);
            ptr_ = o.ptr_;
            count_ = o.count_;
            o.ptr_ = nullptr;
            o.count_ = 0;
        }
        return *this;
    }
    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;

    T* get() const { return ptr_; }
    size_t size() const { return count_; }
    size_t bytes() const { return count_ * sizeof(T); }

private:
    T*     ptr_;
    size_t count_;
};

// ---------------------------------------------------------------------------
// RAII wrapper for CUDA events.
//
// Used for timing kernel execution:
//   CudaEvent start, stop;
//   CHECK_CUDA(ctx, cudaEventRecord(start.get()));
//   launch_kernel<<<...>>>(...);
//   CHECK_CUDA(ctx, cudaEventRecord(stop.get()));
//   CHECK_CUDA(ctx, cudaEventSynchronize(stop.get()));
//   float ms;
//   CHECK_CUDA(ctx, cudaEventElapsedTime(&ms, start.get(), stop.get()));
//
class CudaEvent {
public:
    CudaEvent() {
        cudaError_t err = cudaEventCreate(&ev_);
        if (err != cudaSuccess) {
            ev_ = nullptr;
            throw std::runtime_error(std::string("cudaEventCreate failed: ")
                                     + cudaGetErrorString(err));
        }
    }
    ~CudaEvent() {
        if (ev_) cudaEventDestroy(ev_);
    }
    CudaEvent(CudaEvent&& o) noexcept : ev_(o.ev_) { o.ev_ = nullptr; }
    CudaEvent& operator=(CudaEvent&& o) noexcept {
        if (this != &o) {
            if (ev_) cudaEventDestroy(ev_);
            ev_ = o.ev_;
            o.ev_ = nullptr;
        }
        return *this;
    }
    CudaEvent(const CudaEvent&) = delete;
    CudaEvent& operator=(const CudaEvent&) = delete;

    cudaEvent_t get() const { return ev_; }

private:
    cudaEvent_t ev_ = nullptr;
};

// ---------------------------------------------------------------------------
// RAII wrapper for CUDA streams.
//
// Not strictly needed for the current tests (we use the default stream),
// but provided for completeness so future tests can use explicit streams
// without manual cleanup.
//
class CudaStream {
public:
    CudaStream() {
        cudaError_t err = cudaStreamCreate(&s_);
        if (err != cudaSuccess) {
            s_ = nullptr;
            throw std::runtime_error(std::string("cudaStreamCreate failed: ")
                                     + cudaGetErrorString(err));
        }
    }
    ~CudaStream() {
        if (s_) cudaStreamDestroy(s_);
    }
    CudaStream(CudaStream&& o) noexcept : s_(o.s_) { o.s_ = nullptr; }
    CudaStream& operator=(CudaStream&& o) noexcept {
        if (this != &o) {
            if (s_) cudaStreamDestroy(s_);
            s_ = o.s_;
            o.s_ = nullptr;
        }
        return *this;
    }
    CudaStream(const CudaStream&) = delete;
    CudaStream& operator=(const CudaStream&) = delete;

    cudaStream_t get() const { return s_; }

private:
    cudaStream_t s_ = nullptr;
};

} // namespace testforge

#else  // !TESTFORGE_HAVE_CUDA

// When CUDA is not available, the wrappers are empty stubs so test code
// still compiles. Using them without CUDA will fail at link time, which
// is the right behavior - the test should be guarded by #if TESTFORGE_HAVE_CUDA.

#define CHECK_CUDA(ctx, call)                                                 \
    do {                                                                     \
        ctx.fail("CUDA not available in this build", __FILE__, __LINE__);     \
        throw testforge::AssertionFailure("CUDA not available");              \
    } while (0)

namespace testforge {
template <typename T> class DeviceBuffer {};
class CudaEvent {};
class CudaStream {};
} // namespace testforge

#endif // TESTFORGE_HAVE_CUDA
