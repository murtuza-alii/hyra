"""Human-oriented command-line interface for Mini-Hyra Phase 1."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import AntigravityConfig, RuntimePaths
from .experience_bank import ExperienceBank
from .gpu import discover_gpus
from .manifest import PackageValidationError, build_package, solution_hash
from .task_contract import TASK_TEMPLATE, load_task_contract


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mini-hyra", description="Local research-harness operations: contracts, packages, safety, and experiment history.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="runtime root (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True, title="commands")
    commands.add_parser("init", help="create ignored runtime directories")
    commands.add_parser("doctor", help="report strict-sandbox and optional backend readiness")
    gpu = commands.add_parser("gpu-status", help="show NVIDIA GPUs visible to the harness")
    gpu.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    template = commands.add_parser("task-template", help="print a documented task-contract template")
    template.add_argument("--output", type=Path, help="write the template to a new file instead of stdout")
    validate_task = commands.add_parser("validate-task", help="validate a versioned JSON task contract")
    validate_task.add_argument("contract", type=Path)
    validate_package = commands.add_parser("validate-package", help="validate a solution/ directory and show its immutable manifest")
    validate_package.add_argument("package", type=Path, help="directory containing solution/")
    history = commands.add_parser("history", help="show recent Experience Bank records")
    history.add_argument("--task-id")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    best = commands.add_parser("best", help="show the best valid record for an evaluator version")
    best.add_argument("task_id")
    best.add_argument("evaluator_version")
    best.add_argument("--direction", choices=("minimize", "maximize"), required=True)
    best.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    run_cmd = commands.add_parser("run", help="run autonomous search/optimization loop on a task contract")
    run_cmd.add_argument("contract", type=Path, help="path to task JSON contract")
    run_cmd.add_argument("--agent", choices=("antigravity", "template"), default="antigravity", help="proposal agent engine (default: antigravity)")
    run_cmd.add_argument("--iterations", type=int, help="override maximum iterations")
    run_cmd.add_argument("--non-strict", action="store_true", help="run in non-strict local sandbox mode without hardened launcher")
    run_cmd.add_argument("--json", action="store_true", help="emit machine-readable JSON output")
    return parser



def _emit(value: Any, *, as_json: bool = False) -> None:
    if as_json or not isinstance(value, list):
        print(json.dumps(value, indent=2, sort_keys=True))
        return
    if not value:
        print("No matching experience records.")
        return
    print("RUN ID                            STATUS  ITER  OBJECTIVE                 TIME")
    for item in value:
        metric = item["objective_metrics"][0] if item["objective_metrics"] else None
        objective = "—" if metric is None else f"{metric['name']}={metric['value']} ({metric['direction']})"
        print(f"{item['run_id'][:32]:32}  {item['status']:6}  {item['iteration']:4}  {objective[:24]:24}  {item['execution_time_ms']} ms")


def _package_from_directory(root: Path):
    root = root.resolve()
    solution = root / "solution"
    if not solution.is_dir():
        raise PackageValidationError(f"{root} does not contain solution/")
    files: dict[str, bytes] = {}
    for path in solution.rglob("*"):
        if path.is_symlink():
            raise PackageValidationError(f"symlinks are not allowed: {path.relative_to(root).as_posix()}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return build_package(files)


def _doctor(paths: RuntimePaths) -> int:
    configured = os.getenv("MINI_HYRA_HARDENED_LAUNCHER")
    launcher = Path(configured).expanduser() if configured else None
    antigravity = AntigravityConfig.from_environment(paths)
    ready = launcher is not None and launcher.is_file()
    print(f"Runtime root: {paths.root}")
    print(f"Experience Bank: {paths.state / 'experience_bank.json'}")
    print(f"Strict launcher: {'ready — ' + str(launcher) if ready else 'not configured (strict execution will be rejected)'}")
    print(f"Bash adapter: {'available' if shutil.which('bash') else 'not found'}")
    gpus = discover_gpus()
    print(f"GPU: {', '.join(f'{gpu.index}: {gpu.name} ({gpu.memory_total_mb} MiB)' for gpu in gpus) if gpus else 'no NVIDIA GPU visible'}")
    print(f"Antigravity: {'available — ' + str(antigravity.agy_path) if antigravity.agy_path.is_file() else 'not configured'}")
    print("Status: strict-launcher prerequisite present; verify its OS policy before unattended use" if ready else "Status: ready for contract and package validation")
    return 0


def _best(records: list[dict[str, Any]], direction: str) -> dict[str, Any] | None:
    candidates = [record for record in records if record["status"] == "PASS" and record["objective_metrics"]]
    if not candidates:
        return None
    return (max if direction == "maximize" else min)(candidates, key=lambda record: float(record["objective_metrics"][0]["value"]))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RuntimePaths.from_root(args.root)
    try:
        if args.command == "init":
            paths.ensure()
            print(f"Initialized Mini-Hyra runtime at {paths.root}")
            return 0
        if args.command == "doctor":
            paths.ensure()
            return _doctor(paths)
        if args.command == "gpu-status":
            gpus = [asdict(gpu) for gpu in discover_gpus()]
            if args.json:
                print(json.dumps(gpus, indent=2, sort_keys=True))
            elif not gpus:
                print("No NVIDIA GPU is visible to the harness.")
            else:
                for gpu in gpus:
                    print(f"GPU {gpu['index']}: {gpu['name']} · {gpu['memory_total_mb']} MiB total · {gpu['memory_used_mb']} MiB in use · {gpu['utilization_percent']}% utilization · compute {gpu['compute_capability']}")
            return 0
        if args.command == "task-template":
            contents = json.dumps(TASK_TEMPLATE, indent=2) + "\n"
            if args.output:
                if args.output.exists():
                    raise PackageValidationError(f"refusing to overwrite existing file: {args.output}")
                args.output.write_text(contents, encoding="utf-8")
                print(f"Wrote task-contract template to {args.output}")
            else:
                print(contents, end="")
            return 0
        if args.command == "validate-task":
            task = load_task_contract(args.contract)
            print(f"Valid task contract: {task.task_id} · {task.objective.name} ({task.objective.direction}) · {task.max_iterations} iterations")
            return 0
        if args.command == "validate-package":
            package = _package_from_directory(args.package)
            print(json.dumps({"solution_version": solution_hash(package), "entrypoint": package.entrypoint, "files": [item.__dict__ for item in package.manifest]}, indent=2))
            return 0
        if args.command == "run":
            paths.ensure()
            import asyncio
            import dataclasses
            from .context_agent import ContextAgent
            from .integrations.antigravity_client import AntigravityClient
            from .orchestrator import Orchestrator
            from .proposal_agent import AntigravityProposalAgent, TemplateProposalAgent
            from .models import ObjectiveResult

            task = load_task_contract(args.contract)
            if args.iterations:
                if args.iterations < 1:
                    raise PackageValidationError("--iterations must be at least 1")
                task = dataclasses.replace(task, max_iterations=args.iterations)

            bank = ExperienceBank(paths.state / "experience_bank.json")
            context_agent = ContextAgent(bank)

            if args.agent == "antigravity":
                ag_config = AntigravityConfig.from_environment(paths)
                ag_client = AntigravityClient(ag_config)
                proposal_agent = AntigravityProposalAgent(client=ag_client)
            else:
                proposal_agent = TemplateProposalAgent()

            def _heuristic_evaluator(sandbox, task_contract):
                import re
                for line in reversed(sandbox.stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            data = json.loads(line)
                            if task_contract.objective.name in data:
                                return ObjectiveResult(True, float(data[task_contract.objective.name]), task_contract.objective.name, task_contract.objective.direction, data)
                            if "score" in data:
                                return ObjectiveResult(True, float(data["score"]), task_contract.objective.name, task_contract.objective.direction, data)
                        except Exception:
                            pass
                match = re.search(r"(?:score|metric|" + re.escape(task_contract.objective.name) + r")\s*[:=]\s*([0-9.]+)", sandbox.stdout, re.IGNORECASE)
                if match:
                    return ObjectiveResult(True, float(match.group(1)), task_contract.objective.name, task_contract.objective.direction, {})
                if sandbox.exit_code == 0:
                    score = float(sandbox.execution_time_ms) if "time" in task_contract.objective.name.lower() or "latency" in task_contract.objective.name.lower() else 1.0
                    return ObjectiveResult(True, score, task_contract.objective.name, task_contract.objective.direction, {})
                return ObjectiveResult(False, None, task_contract.objective.name, task_contract.objective.direction, {})

            orchestrator = Orchestrator(
                paths=paths,
                context_agent=context_agent,
                proposal_agent=proposal_agent,
                evaluator=_heuristic_evaluator,
                experience_bank=bank,
            )

            print(f"Starting Mini-Hyra loop for '{task.task_id}' ({task.max_iterations} iterations, agent: {args.agent})...")
            result = asyncio.run(orchestrator.run(task, strict_isolation=not args.non_strict))

            if result is None:
                print("Optimization run ended with no valid solution.")
                return 1
            if args.json:
                print(json.dumps(result.to_dict(), indent=2))
            else:
                metric = result.objective_metrics[0] if result.objective_metrics else {"name": "score", "value": "—"}
                print(f"Best solution: run_id={result.run_id} · {metric['name']}={metric['value']} · time={result.execution_time_ms}ms")
            return 0

        bank = ExperienceBank(paths.state / "experience_bank.json")
        records = bank.records()
        if args.command == "history":
            if args.limit < 1:
                raise PackageValidationError("--limit must be at least 1")
            selected = [record for record in records if not args.task_id or record["task_id"] == args.task_id]
            _emit(selected[-args.limit:][::-1], as_json=args.json)
            return 0
        selected = [record for record in records if record["task_id"] == args.task_id and record["evaluator_version"] == args.evaluator_version]
        record = _best(selected, args.direction)
        if record is None:
            print("No valid scored record exists for that task and evaluator version.")
            return 1
        _emit(record, as_json=args.json)
        return 0
    except (OSError, ValueError, PackageValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
