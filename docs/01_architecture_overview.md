# Mini-Hyra Phase 1 Architecture Overview

## 1. Purpose and Hyra alignment

Mini-Hyra is a local Python 3.11+ research Harness inspired by Tencent Hyra. It is designed for measurable, performance-oriented exploration: generate a complete solution package, run it safely, score it with a task-specific evaluator, preserve the result, and use the accumulated experience to create the next proposals.

This specification deliberately models Hyra's two core agent roles—Context Agent and Proposal Agents. The evaluator is a task plug-in, not a required third autonomous agent. Mini-Hyra is an application-inspired implementation, not a claim to reproduce Tencent's private runtime. Public references: [Tencent-Hunyuan/Hyra-results](https://github.com/Tencent-Hunyuan/Hyra-results) and the [Hyra launch page](https://hy.tencent.com/research/hyra).

Phase 1 remains a modular monolith with local JSON state, an in-process asynchronous queue, isolated child processes, and explicit resource semaphores. No distributed broker or external service is required.

## 2. System topology

```text
                         +----------------------+
                         |    Context Agent     |
                         | EB + inspirations   |
                         | asynchronous producer|
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         |   Inspiration Queue  |
                         | bounded + backpressure|
                         +----------+-----------+
                                    |
                          +---------+----------+
                          |                    |
                          v                    v
                 +--------+--------+  +--------+--------+
                 | Proposal Agent  |  | Proposal Agent  |
                 | consumer worker  |  | consumer worker  |
                 +--------+--------+  +--------+--------+
                          \                    /
                           \                  /
                            v                v
                         +----------------------+
                         | solution/solve.sh    |
                         | complete package     |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Sandboxed Evaluator  |
                         | subprocess + limits  |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Task Evaluator/Grader|
                         | validity + objective |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Experience Bank      |
                         | records + artifacts  |
                         +----------------------+
```

### 2.1 Component responsibilities

| Component | Responsibility | Input | Output |
|---|---|---|---|
| Context Agent | Retrieve and synthesize diverse historical experience; keep the queue supplied | Task contract, EB | Inspiration packages |
| Proposal Agent | Reflect on an inspiration and create an independent solution package | Task, inspiration, prior results | `SolutionPackage` |
| Sandboxed Evaluator | Run the package entrypoint under task-specific isolation and limits | Solution package, sandbox policy | `SandboxResult` |
| Task Evaluator / Grader | Apply validity checks and calculate the task objective | Sandbox result, evaluator contract | `EvaluationResult` |
| Experience Bank | Append immutable runs, manifests, metrics, lessons, and tags; retrieve ranked experience | Experience record | Inspirations and best-so-far result |
| Orchestrator | Own queue lifecycle, leases, iteration budgets, semaphores, and cancellation | Task contract and component results | State transitions and final result |

The evaluator may be deterministic code, a benchmark runner, or an evaluator produced by the optional outer loop. LLM output can explain evidence but cannot override sandbox status, objective score, or security decisions.

## 3. Canonical task contract

```python
from typing import Literal, TypedDict

class Objective(TypedDict):
    name: str
    direction: Literal["minimize", "maximize"]
    target: float | None
    minimum_improvement: float

class TaskContract(TypedDict):
    task_id: str
    task_family: str
    description: str
    solution_entrypoint: str       # solution/solve.sh
    evaluator_version: str         # sha256:<64 lowercase hex chars>
    objective: Objective
    validity_checks: list[str]
    max_iterations: int
    wall_timeout_seconds: float
    memory_limit_mb: int
    allow_network: bool
```

The Harness returns the historical best valid solution and its reproducible artifacts, not merely the latest passing iteration. A simple Python task may use a compatibility adapter around `candidate.py`, but the primary contract is a package with `solution/solve.sh`.

## 4. Data flow

```text
Task Producer -> Orchestrator -> PENDING
                              -> Context Agent queries EB
                              -> inspiration enters bounded queue
Proposal Agent -> claims inspiration -> EVALUATING
               -> writes solution/solve.sh and package files
               -> Sandboxed Evaluator runs isolated package
               -> Task Evaluator computes validity + objective
               -> Orchestrator compares against historical best
               -> EB appends solution manifest, metrics, logs, lessons
               -> LOGGED_TO_EB
               -> best result: COMPLETED
               -> exploratory/rework result: next inspiration -> PENDING
```

The required lifecycle path remains:

```text
PENDING -> EVALUATING -> LOGGED_TO_EB
```

For continued exploration:

```text
LOGGED_TO_EB -> REWORK_REQUIRED -> PENDING
```

`PASS` and `FAIL` are EB record statuses. They are not orchestration states. A valid but non-improving experiment may be `PASS` while `is_best_so_far=false`.

## 5. Producer-consumer design

```python
import asyncio
from asyncio import Queue
from dataclasses import dataclass

@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    task_family: str
    task_text: str
    iteration: int
    max_iterations: int
    evaluator_version: str
    metadata: dict[str, str]

task_queue: Queue[TaskEnvelope] = Queue(maxsize=100)
model_slots = asyncio.Semaphore(2)
sandbox_slots = asyncio.Semaphore(2)
evaluator_slots = asyncio.Semaphore(1)
```

The Context Agent produces inspirations until the queue is full or the task budget is exhausted. Proposal Agents consume independently. Each expensive resource is acquired with a semaphore and released in `finally`; queue depth alone must not over-commit the machine. A full queue applies back-pressure and is never silently dropped.

Workers claim a task under an async lock, persist `EVALUATING`, and always call `queue.task_done()` in a `finally` block. Model calls and subprocess waits must not block the event loop. Each task has one active owner in Phase 1, but many Proposal Agents may process different inspirations concurrently.

## 6. Optional evaluator co-evolution

When a trusted evaluator exists, use the inner loop only:

```text
Context Agent -> Proposal Agents -> solution -> evaluator -> EB
```

When no trusted evaluator exists, enable a versioned outer loop:

```text
1. Generate evaluator E1 from the task description.
2. Freeze E1 and run the inner solution loop.
3. Inspect EB for reward hacking, blind spots, and stale tests.
4. Propose evaluator E2 and validate it against regression/adversarial cases.
5. Freeze E2 and start the next inner round.
```

An evaluator version is immutable. Scores from different evaluator versions are never compared without recording the version.

## 7. Production directory structure

```text
mini_hyra/
├── pyproject.toml
├── src/mini_hyra/
│   ├── main.py
│   ├── config.py
│   ├── models.py                 # one shared contract module
│   ├── orchestrator.py
│   ├── context_agent.py
│   ├── proposal_agent.py
│   ├── evaluator.py
│   ├── sandbox_runner.py
│   ├── experience_bank.py
│   └── prompts/evaluator_system.txt
├── tests/
├── state/
│   ├── tasks_state.json
│   ├── experience_bank.json
│   └── locks/experience_bank.lock
├── solutions/<task_id>/<run_id>/
│   ├── solution/solve.sh
│   ├── manifest.json
│   └── artifacts/
├── logs/runs/<task_id>/<run_id>/
│   ├── stdout.txt
│   ├── stderr.txt
│   ├── evaluation.json
│   └── timing.json
└── sandbox_tmp/<run_id>/           # ephemeral execution copy
```

`state/`, `solutions/`, `logs/`, and `sandbox_tmp/` are runtime data. The execution copy is deleted after retention; the immutable solution package and manifest are retained according to EB policy. On Windows, an allow-listed Bash/WSL adapter may invoke `solve.sh`; the entrypoint remains part of the reproducibility contract.

## 8. Architecture decisions

- **Modular monolith:** simplest useful deployment for one local machine; extract workers only after throughput proves the need.
- **JSON plus artifact directories:** JSON remains inspectable while large code, logs, models, plots, and generated files stay outside the EB document behind immutable manifests.
- **Task-defined evaluator:** validity and objective semantics belong to the task, not to a universal test threshold.
- **Deterministic gates before LLM explanation:** an LLM cannot turn a timeout, security violation, or invalid score into a pass.

