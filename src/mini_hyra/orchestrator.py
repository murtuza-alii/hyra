from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _WorkItem:
    iteration: int
    inspiration: Inspiration


@dataclass(frozen=True)
class _RunOutcome:
    record: ExperienceRecord
    decision: str


class Orchestrator:
    """Owns task lifecycle, immutable persistence, and resource-semaphore boundaries."""

    def __init__(self, *, paths: RuntimePaths, context_agent: ContextAgent, proposal_agent: ProposalAgent,
                 evaluator: TaskEvaluator, experience_bank: ExperienceBank) -> None:
        self.paths, self.context_agent, self.proposal_agent = paths, context_agent, proposal_agent
        self.evaluator, self.experience_bank = evaluator, experience_bank
        self.model_slots, self.sandbox_slots, self.evaluator_slots = asyncio.Semaphore(2), asyncio.Semaphore(2), asyncio.Semaphore(1)
        self.queue: asyncio.Queue[Inspiration] = asyncio.Queue(maxsize=100)
        self.staging = StagingManager(paths)

    async def _run_one(self, task: TaskContract, work: _WorkItem, *, strict_isolation: bool) -> _RunOutcome:
        """Execute exactly one claimed work item and append its immutable record."""
        run_id = uuid.uuid4().hex
        staging_dir = self.staging.stage_path(task.task_id, run_id)
        staging_dir.mkdir(parents=True)
        async with self.model_slots:
            package = await self.proposal_agent.propose(task=task, inspiration=work.inspiration, staging_dir=staging_dir)
        self.staging.persist_immutable(task.task_id, run_id, package)
        async with self.sandbox_slots:
            sandbox = await asyncio.to_thread(run_in_sandbox, package.files, task_id=task.task_id, run_id=run_id, paths=self.paths,
                timeout_seconds=task.wall_timeout_seconds, memory_limit_mb=task.memory_limit_mb, strict_isolation=strict_isolation,
                allow_network=task.allow_network, gpu=task.gpu)
        historical = self.experience_bank.best_score(task.task_id, task.evaluator_version, task.objective.direction)
        async with self.evaluator_slots:
            result = evaluate(sandbox=sandbox, task=task, evaluator=self.evaluator, historical_best=historical, iteration=work.iteration)
        logs = self.paths.logs / "runs" / task.task_id / run_id
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "stdout.txt").write_text(sandbox.stdout, encoding="utf-8")
        (logs / "stderr.txt").write_text(sandbox.stderr, encoding="utf-8")
        (logs / "evaluation.json").write_text(json.dumps(asdict(result), default=str, indent=2), encoding="utf-8")
        (logs / "timing.json").write_text(json.dumps({
            "execution_time_ms": sandbox.execution_time_ms,
            "cpu_time_ms": sandbox.cpu_time_ms,
            "peak_memory_mb": sandbox.peak_memory_mb,
            "gpu": {"name": sandbox.gpu_name, "memory_total_mb": sandbox.gpu_memory_total_mb,
                     "memory_used_mb": sandbox.gpu_memory_used_mb, "utilization_percent": sandbox.gpu_utilization_percent},
            "gpu_policy": asdict(task.gpu),
        }, indent=2), encoding="utf-8")
        record = ExperienceRecord(run_id, task.task_id, task.task_family, work.iteration, solution_hash(package), task.evaluator_version,
            "solution/solve.sh", result.status, result.error_category, result.execution_time_ms,
            {"stdout_excerpt": sandbox.stdout[:4000], "stderr_excerpt": sandbox.stderr[:4000], "exit_code": sandbox.exit_code},
            ([{"name": result.objective_name, "value": result.objective_score, "direction": result.objective_direction}] if result.objective_score is not None else []),
            result.is_best_so_far, list(package.manifest), result.lessons_learned, result.inspiration_tags, self.experience_bank.now())
        self.experience_bank.append(record)
        return _RunOutcome(record, result.decision.value)

    async def run(self, task: TaskContract, *, strict_isolation: bool = True) -> ExperienceRecord | None:
        self.paths.ensure()
        best: ExperienceRecord | None = None
        work_queue: asyncio.Queue[_WorkItem | None] = asyncio.Queue(maxsize=100)
        results: asyncio.Queue[_RunOutcome] = asyncio.Queue()
        # One GPU proposal at a time keeps a 6 GiB laptop GPU from thrashing;
        # CPU-only tasks retain the two-worker Phase 1 default.
        worker_count = 1 if task.gpu.enabled else min(2, task.max_iterations)
        next_iteration = 1

        async def enqueue_next() -> bool:
            nonlocal next_iteration
            if next_iteration > task.max_iterations:
                return False
            inspirations = self.context_agent.synthesize(task)
            inspiration = inspirations[(next_iteration - 1) % len(inspirations)]
            await work_queue.put(_WorkItem(next_iteration, inspiration))
            next_iteration += 1
            return True

        async def worker() -> None:
            while True:
                work = await work_queue.get()
                try:
                    if work is None:
                        return
                    await results.put(await self._run_one(task, work, strict_isolation=strict_isolation))
                finally:
                    work_queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        try:
            for _ in range(worker_count):
                if not await enqueue_next():
                    break
            completed = 0
            while completed < task.max_iterations:
                outcome = await results.get()
                completed += 1
                if outcome.record.is_best_so_far:
                    best = outcome.record
                # A terminal safety/internal failure ends this task rather than
                # repeatedly attempting untrusted work under the same conditions.
                if outcome.decision == "TERMINAL_FAIL":
                    break
                await enqueue_next()
                if next_iteration > task.max_iterations and completed >= next_iteration - 1:
                    break
        finally:
            for _ in workers:
                await work_queue.put(None)
            await work_queue.join()
            await asyncio.gather(*workers)
        return best
