"""Strict JSON task-contract loading for the Mini-Hyra CLI and adapters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .manifest import PackageValidationError, validate_id
from .models import GpuPolicy, Objective, TaskContract

_HASH = re.compile(r"^sha256:[a-f0-9]{64}$")

TASK_TEMPLATE: dict[str, Any] = {
    "task_id": "algorithm-benchmark", "task_family": "benchmark",
    "description": "Optimize the supplied deterministic benchmark.",
    "solution_entrypoint": "solution/solve.sh", "evaluator_version": "sha256:" + "0" * 64,
    "objective": {"name": "runtime_ms", "direction": "minimize", "target": None, "minimum_improvement": 0.0},
    "validity_checks": ["exit-zero", "required-output"], "max_iterations": 10,
    "wall_timeout_seconds": 5.0, "memory_limit_mb": 256, "allow_network": False,
    "gpu": {"enabled": False, "device_index": 0, "min_memory_mb": 0, "memory_limit_mb": None, "require_cuda": False},
}


def load_task_contract(path: Path) -> TaskContract:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PackageValidationError(f"task contract is not valid JSON: {error.msg}") from error
    if not isinstance(document, dict):
        raise PackageValidationError("task contract must be a JSON object")
    required = set(TASK_TEMPLATE)
    # GPU policy was added after the initial contract; CPU-only contracts remain
    # valid and receive the explicit disabled policy.
    document.setdefault("gpu", TASK_TEMPLATE["gpu"])
    if set(document) != required:
        missing, extra = required - set(document), set(document) - required
        details = (["missing " + ", ".join(sorted(missing))] if missing else []) + (["unexpected " + ", ".join(sorted(extra))] if extra else [])
        raise PackageValidationError("task contract fields do not match the versioned contract: " + "; ".join(details))
    objective = document["objective"]
    if not isinstance(objective, dict) or set(objective) != {"name", "direction", "target", "minimum_improvement"}:
        raise PackageValidationError("objective must contain name, direction, target, and minimum_improvement")
    validate_id(str(document["task_id"]), "task_id")
    if not isinstance(document["task_family"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", document["task_family"]):
        raise PackageValidationError("task_family must be lowercase letters, digits, dots, underscores, or hyphens")
    if document["solution_entrypoint"] != "solution/solve.sh":
        raise PackageValidationError("solution_entrypoint must be solution/solve.sh")
    if not isinstance(document["evaluator_version"], str) or not _HASH.fullmatch(document["evaluator_version"]):
        raise PackageValidationError("evaluator_version must be a sha256:<64 lowercase hex> value")
    if not isinstance(objective["name"], str) or not re.fullmatch(r"[a-z0-9._-]{1,64}", objective["name"]):
        raise PackageValidationError("objective.name must be lowercase letters, digits, dots, underscores, or hyphens")
    if objective["direction"] not in {"minimize", "maximize"}:
        raise PackageValidationError("objective.direction must be minimize or maximize")
    if objective["target"] is not None and not isinstance(objective["target"], (int, float)):
        raise PackageValidationError("objective.target must be a number or null")
    if not isinstance(objective["minimum_improvement"], (int, float)) or objective["minimum_improvement"] < 0:
        raise PackageValidationError("objective.minimum_improvement must be a non-negative number")
    if not isinstance(document["description"], str) or not document["description"].strip():
        raise PackageValidationError("description must be a non-empty string")
    if not isinstance(document["validity_checks"], list) or not all(isinstance(item, str) and item for item in document["validity_checks"]):
        raise PackageValidationError("validity_checks must be a list of non-empty strings")
    if not isinstance(document["max_iterations"], int) or not 1 <= document["max_iterations"] <= 10_000:
        raise PackageValidationError("max_iterations must be an integer from 1 to 10000")
    if not isinstance(document["wall_timeout_seconds"], (int, float)) or document["wall_timeout_seconds"] <= 0:
        raise PackageValidationError("wall_timeout_seconds must be positive")
    if not isinstance(document["memory_limit_mb"], int) or document["memory_limit_mb"] < 1:
        raise PackageValidationError("memory_limit_mb must be a positive integer")
    if not isinstance(document["allow_network"], bool):
        raise PackageValidationError("allow_network must be a boolean")
    gpu = document["gpu"]
    if not isinstance(gpu, dict) or set(gpu) != {"enabled", "device_index", "min_memory_mb", "memory_limit_mb", "require_cuda"}:
        raise PackageValidationError("gpu must contain enabled, device_index, min_memory_mb, memory_limit_mb, and require_cuda")
    if (not isinstance(gpu["enabled"], bool) or not isinstance(gpu["require_cuda"], bool)
            or not isinstance(gpu["device_index"], int) or gpu["device_index"] < 0
            or not isinstance(gpu["min_memory_mb"], int) or gpu["min_memory_mb"] < 0
            or (gpu["memory_limit_mb"] is not None and (not isinstance(gpu["memory_limit_mb"], int) or gpu["memory_limit_mb"] < 1))):
        raise PackageValidationError("gpu policy has invalid types or limits")
    if gpu["memory_limit_mb"] is not None and gpu["memory_limit_mb"] < gpu["min_memory_mb"]:
        raise PackageValidationError("gpu.memory_limit_mb must be at least gpu.min_memory_mb")
    return TaskContract(document["task_id"], document["task_family"], document["description"], document["solution_entrypoint"], document["evaluator_version"], Objective(objective["name"], objective["direction"], objective["target"], float(objective["minimum_improvement"])), document["validity_checks"], document["max_iterations"], float(document["wall_timeout_seconds"]), document["memory_limit_mb"], document["allow_network"], GpuPolicy(**gpu))
