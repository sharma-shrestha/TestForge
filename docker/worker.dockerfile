# TestForge worker image.
#
# Ships the C++ worker binary built for CPU-only execution. For GPU
# tests, derive from nvidia/cuda instead - see gpu-worker.dockerfile.

FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testforge

# Build the C++ engine inside the image.
COPY . .
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=OFF \
    && cmake --build build -j \
    && cmake --install build

# Install the Python CLI.
RUN cd python && pip install --break-system-packages .

# Default entrypoint: the testforge CLI.
ENTRYPOINT ["testforge"]
CMD ["--help"]
