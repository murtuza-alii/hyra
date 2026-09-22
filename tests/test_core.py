from pathlib import Path
import asyncio
import json

import mini_hyra.orchestrator as orchestrator_module
from mini_hyra.config import RuntimePaths
from mini_hyra.context_agent import ContextAgent
from mini_hyra.manifest import build_package
from mini_hyra.orchestrator import Orchestrator
from mini_hyra.main import main
from mini_hyra.task_contract import TASK_TEMPLATE

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


def test_orchestrator_consumes_the_iteration_budget(tmp_path: Path) -> None:
    class Agent:
        async def propose(self, **_: object):
            return build_package({"solution/solve.sh": b"#!/bin/sh\nexit 0\n"})

    calls = 0

    def fake_sandbox(*_: object, **__: object) -> SandboxResult:
        nonlocal calls
        calls += 1
        return sandbox()

    paths = RuntimePaths.from_root(tmp_path)
    bank = ExperienceBank(paths.state / "experience_bank.json")
    runner = Orchestrator(paths=paths, context_agent=ContextAgent(bank), proposal_agent=Agent(),
                          evaluator=lambda *_: ObjectiveResult(True, 2.0, "score", "maximize", {}), experience_bank=bank)
    original = orchestrator_module.run_in_sandbox
    orchestrator_module.run_in_sandbox = fake_sandbox
    try:
        result = asyncio.run(runner.run(task(), strict_isolation=False))
    finally:
        orchestrator_module.run_in_sandbox = original
    assert calls == 2
    assert result is not None and result.is_best_so_far


def test_cli_validates_contract_and_package_without_execution(tmp_path: Path) -> None:
    contract = tmp_path / "task.json"
    contract.write_text(json.dumps(TASK_TEMPLATE), encoding="utf-8")
    proposal = tmp_path / "proposal" / "solution"
    proposal.mkdir(parents=True)
    (proposal / "solve.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["validate-task", str(contract)]) == 0
    assert main(["validate-package", str(tmp_path / "proposal")]) == 0


def test_gpu_policy_is_accepted_and_legacy_contract_is_cpu_only(tmp_path: Path) -> None:
    from mini_hyra.task_contract import load_task_contract

    contract = tmp_path / "gpu-task.json"
    gpu_template = {**TASK_TEMPLATE, "gpu": {"enabled": True, "device_index": 0, "min_memory_mb": 1024, "memory_limit_mb": 2048, "require_cuda": True}}
    contract.write_text(json.dumps(gpu_template), encoding="utf-8")
    task = load_task_contract(contract)
    assert task.gpu.enabled and task.gpu.memory_limit_mb == 2048
    legacy = {key: value for key, value in TASK_TEMPLATE.items() if key != "gpu"}
    contract.write_text(json.dumps(legacy), encoding="utf-8")
    assert not load_task_contract(contract).gpu.enabled


def test_markdown_extraction_and_proposal_agents(tmp_path: Path) -> None:
    from mini_hyra.proposal_agent import (
        extract_files_from_markdown,
        TemplateProposalAgent,
        AntigravityProposalAgent
    )
    from mini_hyra.context_agent import Inspiration
    from mini_hyra.integrations.antigravity_client import AgentResponse

    md_annotated = (
        'Here is the solution:\n'
        '```bash file="solution/solve.sh"\n'
        '#!/bin/sh\n'
        'python3 solution/main.py\n'
        '```\n'
        '```python file="solution/main.py"\n'
        'print("score: 42")\n'
        '```\n'
    )
    files = extract_files_from_markdown(md_annotated)
    assert "solution/solve.sh" in files and "solution/main.py" in files
    assert "python3" in files["solution/solve.sh"]

    md_single_python = (
        '```python\n'
        'print("optimized kernel")\n'
        '```\n'
    )
    files_single = extract_files_from_markdown(md_single_python)
    assert "solution/solve.sh" in files_single
    assert "solution/main.py" in files_single

    staging_template = tmp_path / "stage_template"
    staging_template.mkdir()
    template_agent = TemplateProposalAgent()
    pkg = asyncio.run(template_agent.propose(
        task=task(),
        inspiration=Inspiration([], "establish a valid deterministic baseline", "No historical evidence is available.", ["exit-zero"]),
        staging_dir=staging_template
    ))
    assert "solution/solve.sh" in pkg.files

    class MockClient:
        async def send_message(self, **_: object) -> AgentResponse:
            return AgentResponse(
                success=True,
                content=md_annotated,
                conversation_id="test-conv-123",
                session_role="proposal",
                transcript_path=None,
                tool_calls_observed=0,
                elapsed_ms=10,
                error=None
            )

    staging_antigravity = tmp_path / "stage_antigravity"
    staging_antigravity.mkdir()
    ag_agent = AntigravityProposalAgent(client=MockClient())
    ag_pkg = asyncio.run(ag_agent.propose(
        task=task(),
        inspiration=Inspiration(["run_0"], "improve baseline", "Explore faster sort algorithm.", ["exit-zero"]),
        staging_dir=staging_antigravity
    ))
    assert "solution/solve.sh" in ag_pkg.files
    assert "solution/main.py" in ag_pkg.files


def test_cli_run_command_with_template_agent(tmp_path: Path) -> None:
    contract = tmp_path / "task.json"
    contract.write_text(json.dumps(TASK_TEMPLATE), encoding="utf-8")
    assert main(["--root", str(tmp_path), "init"]) == 0
    # Run with template agent and non-strict mode
    code = main([
        "--root", str(tmp_path),
        "run", str(contract),
        "--agent", "template",
        "--iterations", "1",
        "--non-strict"
    ])
    assert code == 0
    assert main(["--root", str(tmp_path), "history"]) == 0



