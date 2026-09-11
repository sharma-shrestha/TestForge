# GPU worker image.
#
# Builds on the NVIDIA CUDA base image and adds TestForge on top. Use this
# when running GPU tests via `docker run --gpus all`.
#
# Build:
#   docker build -f docker/gpu-worker.dockerfile -t testforge-gpu .
# Run:
#   docker run --rm --gpus all testforge-gpu run

FROM nvidia/cuda:12.4.0-devel-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /testforge
COPY . .

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTESTFORGE_ENABLE_CUDA=ON \
    && cmake --build build -j

RUN cd python && pip install --break-system-packages .

ENTRYPOINT ["testforge"]
CMD ["--help"]
