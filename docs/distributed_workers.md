# Distributed workers (design note)

This document describes the *planned* distributed worker protocol. The
single-machine worker pool (in `scheduler.py`) works today; distribution
over the network is a near-term roadmap item.

## Why we want this

On a single machine you hit a ceiling: tests compete for CPU, memory,
and (critically) GPU. If you have 8 GPU tests and one GPU, parallelism
doesn't help - they have to serialize. Distributed workers let you:

- Run CPU tests on cheap CPU-only machines.
- Run GPU tests on GPU machines, one test per GPU for isolation.
- Scale horizontally as the test suite grows.

## Protocol

```
Worker registration:

    POST /workers/register
    {
        "worker_id": "host-foo-1234",
        "capabilities": ["cpu", "gpu"],
        "gpu_count": 1,
        "gpu_device_name": "NVIDIA RTX 4090"
    }
    -> 200 OK {"session_id": "...", "heartbeat_interval_s": 15}

Heartbeat:

    POST /workers/{id}/heartbeat
    {"status": "idle|busy", "current_test": "GPU.MatrixMultiply"|"", "load": 0.42}

Job pull (long-poll):

    GET /workers/{id}/jobs?wait=30s
    -> 200 OK {"job_id": "...", "tests": [...], "binary": "...", "kind": "cpp_engine"}
       or 204 No Content (no work)

Job result push:

    POST /workers/{id}/jobs/{job_id}/results
    { ... same JSON as the local worker stdout ... }

Worker unregister:

    DELETE /workers/{id}
```

## Failure modes

- **Worker dies mid-job.** Orchestrator notices heartbeat timeout after
  `2 * heartbeat_interval_s`. Job is requeued to a different worker.
- **Worker reports a crash (SEGFAULT).** Result is recorded with
  `status="crash"` and the test is marked failed. Orchestrator can
  optionally retry on a different worker.
- **Orchestrator restarts.** Workers reconnect; in-flight jobs are
  lost. (We accept this - orchestrator restarts are rare and tests
  rerun cheaply.)
- **Network partition.** Heartbeat timeout fires on the orchestrator
  side; worker retries registration with backoff.

## What's not in this design

- **No streaming results.** Results are pushed once per job completion.
  For long jobs we may want a streaming variant later, but the
  simpler protocol is better to start with.
- **No work stealing.** A worker that finishes its job pulls the next
  one; it doesn't steal from a slower worker. We don't expect
  stragglers to be a big problem given the test granularity.
- **No multi-GPU within a single worker.** Each GPU worker claims one
  GPU at registration time. Multi-GPU tests would need a separate
  "multi_gpu" capability and a different job type.

## Current status

The protocol is documented here but not implemented. The single-machine
scheduler (`scheduler.py`) is the production path today. Implementing
distributed workers is roughly:

1. Stand up a FastAPI orchestrator server with the endpoints above.
2. Refactor the worker pool to either spawn subprocesses (current) or
   pull jobs from an HTTP endpoint (new).
3. Add a heartbeat thread to the worker binary.
4. Add requeue-on-timeout logic to the orchestrator.

Each step is a few days of work. The reason we haven't done it yet is
that the test suite in this project doesn't yet need it - the single-
machine pool handles it fine.
