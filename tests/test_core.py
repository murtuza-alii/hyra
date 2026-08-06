from pathlib import Path

from mini_hyra.evaluator import evaluate
from mini_hyra.experience_bank import ExperienceBank
from mini_hyra.manifest import PackageValidationError, build_package
from mini_hyra.models import Objective, ObjectiveResult, SandboxResult, TaskContract


def task() -> TaskContract:
    return TaskContract("demo", "benchmark", "demo", "solution/solve.sh", "sha256:" + "a" * 64,
        Objective("score", "maximize", minimum_improvement=0.1), ["exit-zero"], 2, 5, 256)


def sandbox() -> SandboxResult:
    return SandboxResult("PASS", "SUCCESS", 0, "ok", "", None, None, 5, None, None, False, False, None)


def test_package_requires_canonical_entrypoint() -> None:
    try:
        build_package({"solution/main.py": b"print('x')"})
    except PackageValidationError:
        return
    raise AssertionError("missing solve.sh must be rejected")


def test_first_valid_result_is_best() -> None:
    result = evaluate(sandbox=sandbox(), task=task(), evaluator=lambda *_: ObjectiveResult(True, 2.0, "score", "maximize", {}), historical_best=None, iteration=1)
    assert result.is_best_so_far and result.status == "PASS"


def test_experience_bank_is_append_only(tmp_path: Path) -> None:
    bank = ExperienceBank(tmp_path / "experience_bank.json")
    from mini_hyra.models import ErrorCategory, ExperienceRecord
    record = ExperienceRecord("run1", "demo", "benchmark", 1, "sha256:" + "a" * 64, "sha256:" + "b" * 64,
        "solution/solve.sh", "PASS", ErrorCategory.NONE, 1, {"stdout_excerpt": "", "stderr_excerpt": "", "exit_code": 0},
        [{"name": "score", "value": 1.0, "direction": "maximize"}], True, [], ["baseline"], ["valid"], bank.now())
    bank.append(record)
    assert bank.best_score("demo", record.evaluator_version, "maximize") == 1.0
