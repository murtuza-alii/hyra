from __future__ import annotations

from collections.abc import Callable

from .models import Decision, ErrorCategory, EvaluationResult, ObjectiveResult, SandboxResult, TaskContract

TaskEvaluator = Callable[[SandboxResult, TaskContract], ObjectiveResult]


def _error_category(sandbox: SandboxResult) -> ErrorCategory:
    lookup = {
        "SYNTAX_ERROR": ErrorCategory.SYNTAX_ERROR, "TEST_FAILURE": ErrorCategory.TEST_FAILURE,
        "RUNTIME_ERROR": ErrorCategory.RUNTIME_ERROR, "TIMEOUT": ErrorCategory.TIMEOUT,
        "RESOURCE_LIMIT": ErrorCategory.RESOURCE_LIMIT, "SECURITY_VIOLATION": ErrorCategory.SECURITY_VIOLATION,
        "GPU_UNAVAILABLE": ErrorCategory.GPU_UNAVAILABLE,
        "INTERNAL_ERROR": ErrorCategory.INTERNAL_ERROR,
    }
    return lookup.get(sandbox.status_code, ErrorCategory.UNKNOWN)


def evaluate(*, sandbox: SandboxResult, task: TaskContract, evaluator: TaskEvaluator,
             historical_best: float | None, iteration: int) -> EvaluationResult:
    if sandbox.status != "PASS":
        category = _error_category(sandbox)
        terminal = category in {ErrorCategory.SECURITY_VIOLATION, ErrorCategory.INTERNAL_ERROR}
        return EvaluationResult(Decision.TERMINAL_FAIL if terminal or iteration >= task.max_iterations else Decision.REWORK,
            "FAIL", category, False, None, task.objective.name, task.objective.direction, historical_best, False,
            0, sandbox.execution_time_ms, [f"Sandbox failed: {category.value.lower()}."], [category.value.lower().replace("_", "-")])
    objective = evaluator(sandbox, task)
    if not objective.valid or objective.score is None:
        return EvaluationResult(Decision.TERMINAL_FAIL if iteration >= task.max_iterations else Decision.REWORK,
            "FAIL", ErrorCategory.TEST_FAILURE, False, objective.score, objective.metric_name, objective.direction,
            historical_best, False, 100, sandbox.execution_time_ms, ["Task evaluator rejected the package output."], ["test-failure"])
    first_valid = historical_best is None
    if task.objective.direction == "maximize":
        improved = first_valid or objective.score >= historical_best + task.objective.minimum_improvement
    else:
        improved = first_valid or objective.score <= historical_best - task.objective.minimum_improvement
    return EvaluationResult(Decision.ACCEPT_BEST if improved else Decision.ACCEPT_VALID, "PASS", ErrorCategory.NONE,
        True, objective.score, objective.metric_name, objective.direction, historical_best, improved, 100,
        sandbox.execution_time_ms, ["Valid package evaluated deterministically."], ["valid", "best" if improved else "exploratory"])
