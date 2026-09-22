"""Read-only NVIDIA GPU discovery used for task admission and operator status."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class GpuInfo:
    index: int
    name: str
    driver_version: str
    memory_total_mb: int
    memory_used_mb: int
    utilization_percent: int
    compute_capability: str


def discover_gpus() -> list[GpuInfo]:
    """Return NVIDIA GPUs visible to the harness without executing proposal code."""
    binary = shutil.which("nvidia-smi")
    if binary is None:
        return []
    query = "index,name,driver_version,memory.total,memory.used,utilization.gpu,compute_cap"
    try:
        completed = subprocess.run([binary, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=5, check=False, shell=False)
    except OSError:
        return []
    if completed.returncode:
        return []
    devices: list[GpuInfo] = []
    for line in completed.stdout.splitlines():
        fields = [item.strip() for item in line.split(",")]
        if len(fields) != 7:
            continue
        try:
            devices.append(GpuInfo(int(fields[0]), fields[1], fields[2], int(fields[3]), int(fields[4]), int(fields[5]), fields[6]))
        except ValueError:
            continue
    return devices
