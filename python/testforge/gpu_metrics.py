"""GPU metrics collector.

Wraps nvidia-smi to get current GPU utilization / memory usage. Degrades
gracefully when no GPU is available - every metric returns None instead of
raising, and `is_available()` lets callers short-circuit entirely.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GPUSnapshot:
    device_name: str = ""
    utilization_pct: Optional[float] = None
    memory_used_mb: Optional[int] = None
    memory_total_mb: Optional[int] = None
    temperature_c: Optional[int] = None
    power_w: Optional[float] = None


_NVML_UTIL = re.compile(r"(\d+)\s*%")
_NVML_MEM  = re.compile(r"(\d+)\s*MiB\s*/\s*(\d+)\s*MiB")
_NVML_TEMP = re.compile(r"(\d+)\s*C")
_NVML_PWR  = re.compile(r"([\d.]+)\s*W")
_NVML_NAME = re.compile(r"Name:\s*(.+)")


class GPUMetricsCollector:
    def __init__(self, smi_path: str = "nvidia-smi"):
        self.smi_path = smi_path
        self._available = shutil.which(smi_path) is not None

    def is_available(self) -> bool:
        return self._available

    def snapshot(self) -> GPUSnapshot:
        if not self._available:
            return GPUSnapshot()
        try:
            proc = subprocess.run(
                [self.smi_path, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode != 0:
                return GPUSnapshot()
            # csv,noheader: "NVIDIA GeForce RTX 4090, 5, 1234, 24576, 45, 25.5"
            fields = [f.strip() for f in proc.stdout.splitlines()[0].split(",")]
            if len(fields) < 6:
                return GPUSnapshot()
            return GPUSnapshot(
                device_name=fields[0],
                utilization_pct=float(fields[1]) if fields[1] != "[N/A]" else None,
                memory_used_mb=int(fields[2]) if fields[2] != "[N/A]" else None,
                memory_total_mb=int(fields[3]) if fields[3] != "[N/A]" else None,
                temperature_c=int(fields[4]) if fields[4] != "[N/A]" else None,
                power_w=float(fields[5]) if fields[5] != "[N/A]" else None,
            )
        except Exception:
            return GPUSnapshot()
