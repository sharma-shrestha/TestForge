"""Distributed worker protocol (reference implementation).

This is a stub of the protocol documented in docs/distributed_workers.md.
It is not yet wired into the main scheduler - the single-machine worker
pool in scheduler.py is the production path today.

The stub is here so that the protocol can be reviewed and iterated on
without coupling it to the orchestrator's main flow yet.

When this is production-ready, scheduler.py will gain a flag to switch
between "local subprocess pool" and "remote worker pool", and this
module will provide the remote worker client + server.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WorkerSession:
    worker_id: str
    session_id: str
    capabilities: list[str]
    heartbeat_interval_s: int = 15
    last_heartbeat: float = field(default_factory=time.time)
    status: str = "idle"             # idle | busy | dead
    current_test: str = ""


@dataclass
class Job:
    job_id: str
    tests: list[dict]
    binary: str
    kind: str
    assigned_to: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    results: list[dict] = field(default_factory=list)


class DistributedOrchestrator:
    """In-memory stub of the orchestrator's worker-management side.

    A real implementation would back this with persistent storage so
    orchestrator restarts don't lose job state. The protocol surface
    is what we want to nail down here; storage is a detail.
    """

    def __init__(self):
        self.workers: dict[str, WorkerSession] = {}
        self.pending_jobs: list[Job] = []
        self.in_flight: dict[str, Job] = {}      # job_id -> Job
        self.completed: list[Job] = []

    # ---------- worker lifecycle ----------
    def register_worker(self, worker_id: str, capabilities: list[str]) -> WorkerSession:
        session = WorkerSession(
            worker_id=worker_id,
            session_id=str(uuid.uuid4()),
            capabilities=capabilities,
        )
        self.workers[worker_id] = session
        return session

    def heartbeat(self, worker_id: str, status: str, current_test: str = "") -> bool:
        w = self.workers.get(worker_id)
        if not w:
            return False
        w.last_heartbeat = time.time()
        w.status = status
        w.current_test = current_test
        return True

    def unregister_worker(self, worker_id: str) -> None:
        self.workers.pop(worker_id, None)

    def reap_dead_workers(self, timeout_s: int = 60) -> list[str]:
        """Mark workers that haven't heartbeated recently as dead.

        Returns the list of worker IDs that were reaped. Their in-flight
        jobs would need to be requeued in a real implementation.
        """
        now = time.time()
        reaped = []
        for wid, w in list(self.workers.items()):
            if now - w.last_heartbeat > timeout_s:
                w.status = "dead"
                reaped.append(wid)
        return reaped

    # ---------- job lifecycle ----------
    def enqueue_job(self, tests: list[dict], binary: str, kind: str) -> Job:
        job = Job(
            job_id=str(uuid.uuid4()),
            tests=tests,
            binary=binary,
            kind=kind,
        )
        self.pending_jobs.append(job)
        return job

    def pull_job(self, worker_id: str, wait_s: int = 0) -> Optional[Job]:
        """Pull the next pending job for a worker.

        Returns None if no job is available (optionally after waiting
        up to `wait_s` seconds - long-poll semantics).
        """
        deadline = time.time() + wait_s
        while True:
            if self.pending_jobs:
                job = self.pending_jobs.pop(0)
                job.assigned_to = worker_id
                job.started_at = time.time()
                self.in_flight[job.job_id] = job
                w = self.workers.get(worker_id)
                if w:
                    w.status = "busy"
                return job
            if time.time() >= deadline:
                return None
            time.sleep(0.1)

    def complete_job(self, worker_id: str, job_id: str, results: list[dict]) -> bool:
        job = self.in_flight.pop(job_id, None)
        if not job:
            return False
        job.results = results
        job.completed_at = time.time()
        self.completed.append(job)
        w = self.workers.get(worker_id)
        if w:
            w.status = "idle"
            w.current_test = ""
        return True

    def requeue_in_flight_for(self, worker_id: str) -> int:
        """Requeue all in-flight jobs assigned to a (presumed dead) worker."""
        requeued = 0
        for jid, job in list(self.in_flight.items()):
            if job.assigned_to == worker_id:
                self.in_flight.pop(jid)
                job.assigned_to = None
                job.started_at = None
                self.pending_jobs.append(job)
                requeued += 1
        return requeued


# Example of the wire format used between worker and orchestrator.
# This is what an HTTP body looks like for each endpoint.

EXAMPLE_REGISTER_REQUEST = json.dumps({
    "worker_id": "host-foo-1234",
    "capabilities": ["cpu", "gpu"],
    "gpu_count": 1,
    "gpu_device_name": "NVIDIA RTX 4090",
})

EXAMPLE_REGISTER_RESPONSE = json.dumps({
    "session_id": "abc-123-def",
    "heartbeat_interval_s": 15,
})

EXAMPLE_HEARTBEAT_REQUEST = json.dumps({
    "status": "busy",
    "current_test": "GPU.MatrixMultiply",
    "load": 0.42,
})

EXAMPLE_JOB_RESPONSE = json.dumps({
    "job_id": "job-xyz",
    "tests": [
        {"name": "GPU.VectorAdd", "binary": "build/bin/example_gpu_tests"},
        {"name": "GPU.MatrixMultiply", "binary": "build/bin/example_gpu_tests"},
    ],
    "binary": "build/bin/example_gpu_tests",
    "kind": "cpp_engine",
})
