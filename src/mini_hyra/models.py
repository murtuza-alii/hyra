from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping


Direction = Literal["minimize", "maximize"]
Status = Literal["PASS", "FAIL"]


class ErrorCategory(str, Enum):
    NONE = "NONE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TEST_FAILURE = "TEST_FAILURE"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN = "UNKNOWN"


class LifecycleState(str, Enum):
    PENDING = "PENDING"
    EVALUATING = "EVALUATING"
    LOGGED_TO_EB = "LOGGED_TO_EB"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    COMPLETED = "COMPLETED"
    TERMINAL_FAIL = "TERMINAL_FAIL"


class Decision(str, Enum):
    ACCEPT_BEST = "ACCEPT_BEST"
    ACCEPT_VALID = "ACCEPT_VALID"
    REWORK = "REWORK"
    TERMINAL_FAIL = "TERMINAL_FAIL"
    EVOLVE_EVALUATOR = "EVOLVE_EVALUATOR"


@dataclass(frozen=True)
class Objective:
    name: str
    direction: Direction
    target: float | None = None
    minimum_improvement: float = 0.0


@dataclass(frozen=True)
class TaskContract:
    task_id: str
    task_family: str
    description: str
    solution_entrypoint: str
    evaluator_version: str
    objective: Objective
    validity_checks: list[str]
    max_iterations: int
    wall_timeout_seconds: float
    memory_limit_mb: int
    allow_network: bool = False


@dataclass(frozen=True)
class ArtifactManifestItem:
    relative_path: str
    kind: Literal["source", "config", "log", "model", "plot", "result", "other"]
    sha256: str
    bytes: int


@dataclass(frozen=True)
class SolutionPackage:
    files: Mapping[str, bytes]
    manifest: tuple[ArtifactManifestItem, ...]
    entrypoint: str = "solution/solve.sh"


@dataclass(frozen=True)
class SandboxResult:
    status: Status
    status_code: str
    exit_code: int | None
    stdout: str
    stderr: str
    exception_type: str | None
    exception_message: str | None
    execution_time_ms: int
    peak_memory_mb: int | None
    cpu_time_ms: int | None
    output_truncated: bool
    isolation_degraded: bool
    sandbox_path: str | None


@dataclass(frozen=True)
class ObjectiveResult:
    valid: bool
    score: float | None
    metric_name: str
    direction: Direction
    details: Mapping[str, str | int | float | bool]


@dataclass(frozen=True)
class EvaluationResult:
    decision: Decision
    status: Status
    error_category: ErrorCategory
    valid: bool
    objective_score: float | None
    objective_name: str
    objective_direction: Direction
    best_objective_score: float | None
    is_best_so_far: bool
    efficiency_score: int
    execution_time_ms: int
    lessons_learned: list[str]
    inspiration_tags: list[str]


@dataclass(frozen=True)
class ExperienceRecord:
    run_id: str
    task_id: str
    task_family: str
    iteration: int
    solution_version: str
    evaluator_version: str
    solution_entrypoint: str
    status: Status
    error_category: ErrorCategory
    execution_time_ms: int
    stdout_stderr_summary: Mapping[str, str | int | None]
    objective_metrics: list[Mapping[str, str | float]]
    is_best_so_far: bool
    artifact_manifest: list[ArtifactManifestItem]
    lessons_learned: list[str]
    inspiration_tags: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["error_category"] = self.error_category.value
        return value


def as_jsonable(value: Any) -> dict[str, Any]:
    """Convert a supported dataclass contract to a JSON-safe dictionary."""
    result = asdict(value)
    for key, item in result.items():
        if isinstance(item, Enum):
            result[key] = item.value
    return result
