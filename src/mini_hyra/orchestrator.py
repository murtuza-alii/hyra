from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .context_agent import ContextAgent, Inspiration
from .evaluator import TaskEvaluator, evaluate
from .experience_bank import ExperienceBank
from .manifest import solution_hash
from .models import ExperienceRecord, SolutionPackage, TaskContract
from .proposal_agent import ProposalAgent
from .sandbox_runner import run_in_sandbox
from .staging_manager import StagingManager
from .config import RuntimePaths


class Orchestrator:
    """Owns task lifecycle, immutable persistence, and resource-semaphore boundaries."""

    def __init__(self, *, paths: RuntimePaths, context_agent: ContextAgent, proposal_agent: ProposalAgent,
                 evaluator: TaskEvaluator, experience_bank: ExperienceBank) -> None:
        self.paths, self.context_agent, self.proposal_agent = paths, context_agent, proposal_agent
        self.evaluator, self.experience_bank = evaluator, experience_bank
        self.model_slots, self.sandbox_slots, self.evaluator_slots = asyncio.Semaphore(2), asyncio.Semaphore(2), asyncio.Semaphore(1)
        self.queue: asyncio.Queue[Inspiration] = asyncio.Queue(maxsize=100)
        self.staging = StagingManager(paths)

    async def run(self, task: TaskContract, *, strict_isolation: bool = True) -> ExperienceRecord | None:
        self.paths.ensure()
        for inspiration in self.context_agent.synthesize(task):
            await self.queue.put(inspiration)
        best: ExperienceRecord | None = None
        while not self.queue.empty() and (best is None or best.iteration < task.max_iterations):
            inspiration = await self.queue.get()
            try:
                iteration = (best.iteration if best else 0) + 1
                run_id = uuid.uuid4().hex
                staging_dir = self.staging.stage_path(task.task_id, run_id)
                staging_dir.mkdir(parents=True)
                async with self.model_slots:
                    package = await self.proposal_agent.propose(task=task, inspiration=inspiration, staging_dir=staging_dir)
                self.staging.persist_immutable(task.task_id, run_id, package)
                async with self.sandbox_slots:
                    sandbox = await asyncio.to_thread(run_in_sandbox, package.files, task_id=task.task_id, run_id=run_id, paths=self.paths,
                        timeout_seconds=task.wall_timeout_seconds, memory_limit_mb=task.memory_limit_mb, strict_isolation=strict_isolation, allow_network=task.allow_network)
                historical = self.experience_bank.best_score(task.task_id, task.evaluator_version, task.objective.direction)
                async with self.evaluator_slots:
                    result = evaluate(sandbox=sandbox, task=task, evaluator=self.evaluator, historical_best=historical, iteration=iteration)
                logs = self.paths.logs / "runs" / task.task_id / run_id
                logs.mkdir(parents=True, exist_ok=True)
                (logs / "stdout.txt").write_text(sandbox.stdout, encoding="utf-8")
                (logs / "stderr.txt").write_text(sandbox.stderr, encoding="utf-8")
                (logs / "evaluation.json").write_text(json.dumps(asdict(result), default=str, indent=2), encoding="utf-8")
                record = ExperienceRecord(run_id, task.task_id, task.task_family, iteration, solution_hash(package), task.evaluator_version,
                    "solution/solve.sh", result.status, result.error_category, result.execution_time_ms,
                    {"stdout_excerpt": sandbox.stdout[:4000], "stderr_excerpt": sandbox.stderr[:4000], "exit_code": sandbox.exit_code},
                    ([{"name": result.objective_name, "value": result.objective_score, "direction": result.objective_direction}] if result.objective_score is not None else []),
                    result.is_best_so_far, list(package.manifest), result.lessons_learned, result.inspiration_tags, self.experience_bank.now())
                self.experience_bank.append(record)
                if record.is_best_so_far:
                    best = record
            finally:
                self.queue.task_done()
        return best
