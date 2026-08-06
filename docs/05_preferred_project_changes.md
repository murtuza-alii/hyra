# Mini-Hyra Preferred Project Changes

## Executive recommendation

Treat Mini-Hyra as a lightweight research Harness, not only as a Python unit-test retry loop. The highest-value implementation is a measurable, reproducible optimization system that generates complete solution packages, runs them safely, records artifacts and metrics, and returns the best historical solution.

The preferred first application is an AI-for-AI micro-benchmark: algorithm optimization, kernel optimization, training-configuration search, or another task with a deterministic score. This gives Mini-Hyra a real objective while keeping Phase 1 local and affordable.

## Priority order

| Priority | Change | Benefit | Recommendation |
|---|---|---|---|
| P0 | Replace `candidate.py` as the primary contract with `solution/solve.sh` | Supports real research, engineering, scientific, and creative tasks | Required |
| P0 | Add a task-specific evaluator contract | Makes scores meaningful instead of relying on universal pass thresholds | Required |
| P0 | Store best-so-far solutions and objective metrics | Enables genuine recursive improvement | Required |
| P0 | Expand Experience Bank with artifact manifests and evaluator versions | Preserves reusable knowledge and reproducibility | Required |
| P0 | Add semaphore-controlled model, sandbox, and evaluator concurrency | Keeps local resources saturated without over-committing them | Required |
| P1 | Add evaluator co-evolution as an optional outer loop | Handles tasks without a trusted evaluator and reduces reward hacking | Recommended after inner loop works |
| P1 | Add task profiles for timeout, CPU, memory, and dependency policy | Supports both micro-tests and longer research jobs | Recommended |
| P1 | Add result comparison and regression tests | Prevents accidental acceptance of worse solutions | Recommended |
| P2 | Replace JSON-only indexing with SQLite or a vector index | Improves retrieval at larger history sizes | Defer until JSON limits are reached |
| P2 | Add distributed workers or an external queue | Enables multi-host scaling | Defer until one-machine throughput is proven insufficient |

## 1. Target project contract

Every task should be represented by a versioned contract:

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
    solution_entrypoint: str       # always "solution/solve.sh"
    evaluator_version: str         # sha256:<64 lowercase hex chars>
    objective: Objective
    validity_checks: list[str]
    max_iterations: int
    wall_timeout_seconds: float
    memory_limit_mb: int
    allow_network: bool
```

The task evaluator must return:

```python
class ObjectiveResult(TypedDict):
    valid: bool
    score: float | None
    metric_name: str
    direction: Literal["minimize", "maximize"]
    details: dict[str, str | int | float | bool]
```

`valid` is a safety and correctness gate. `score` determines whether the result improves the historical best. Do not use a universal `functional_score >= 80` rule as the primary objective for every task.

## 2. Preferred module changes

### `models.py`

Add shared types for:

- `TaskContract` and `Objective`;
- `SolutionPackage` and immutable artifact manifest;
- `EvaluatorContract` and `ObjectiveResult`;
- `ExperienceRecord` with `solution_version`, `evaluator_version`, `objective_metrics`, and `is_best_so_far`;
- lifecycle state and resource-budget literals.

All modules must import these types from one location. Do not duplicate status strings or score semantics in individual agents.

### `proposal_agent.py`

Change the output from a single code string to a complete package:

```text
solution/
├── solve.sh
├── source files
├── configuration files
├── local tests or probes
└── README.md
```

`solve.sh` must be deterministic, executable, and return a non-zero exit code on invalid output. The proposal agent may create files, but it must not write directly to the host runtime directories or Experience Bank.

### `sandbox_runner.py`

Use the package entrypoint as the canonical execution path. Keep the current `subprocess` and `TemporaryDirectory` design, but add:

- a `solution_files` input mapping;
- an `entrypoint` argument defaulting to `solution/solve.sh`;
- task-specific timeout, memory, CPU, output, and dependency policy;
- process-tree cleanup;
- immutable input and output manifests;
- explicit degraded-isolation reporting.

Keep `candidate.py` only as a compatibility adapter for simple Python tasks.

### `evaluator.py`

Split grading into two decisions:

1. **Validity:** syntax, required output, safety, test correctness, and resource compliance.
2. **Improvement:** comparison against the historical best using the task objective.

Accept a result as the new best only when:

```text
valid == true
and score is not null
and score improves the best score by at least minimum_improvement
```

The first valid solution may become the baseline even without an improvement. A valid but non-improving solution should remain an exploratory `PASS` record, not be treated as a failed experiment.

### `experience_bank.py`

Keep JSON for Phase 1, but store large data outside the JSON file. Each record should reference:

```text
solutions/<task_id>/<run_id>/solution/
solutions/<task_id>/<run_id>/artifacts/
logs/runs/<task_id>/<run_id>/
```

Add these fields to the record contract:

- `task_family`;
- `solution_version`;
- `evaluator_version`;
- `objective_metrics`;
- `is_best_so_far`;
- `artifact_manifest`;
- `solution_entrypoint`.

Retain the required operational fields already defined in `02_experience_bank_spec.md`: task identity, iteration, status, error category, execution time, output summary, lessons, and inspiration tags.

## 3. Experience Bank retrieval policy

The Context Agent should retrieve a balanced set of experiences:

- the top historical solutions by objective score;
- recent failures with distinct error fingerprints;
- diverse approaches, not only the nearest text match;
- the current evaluator version and any known evaluator weaknesses;
- relevant artifacts, logs, and lessons within a strict context budget.

Use this ranking concept:

```text
retrieval_score =
    0.35 * task_similarity
  + 0.25 * objective_quality
  + 0.15 * novelty
  + 0.15 * recency
  + 0.10 * failure_relevance
```

The generated inspiration must distinguish historical evidence from instructions. It must never be able to alter sandbox permissions, evaluator thresholds, or resource limits.

## 4. Producer-consumer and resource control

Use one Context Agent producer and multiple Proposal Agent consumers. Control each bottleneck separately:

```python
queue_capacity = 100
model_slots = asyncio.Semaphore(2)
sandbox_slots = asyncio.Semaphore(2)
evaluator_slots = asyncio.Semaphore(1)
```

Acquire and release every semaphore in `try/finally`. The producer should maintain enough queued inspirations to keep consumers busy, but must stop producing when the queue is full or the task budget is exhausted. This is closer to Hyra's resource-saturation model than a fixed serial retry loop.

## 5. Optional evaluator co-evolution

Implement this only after the trusted-evaluator inner loop is stable:

```text
1. Generate an initial evaluator from the task description.
2. Freeze evaluator version E1.
3. Run the inner solution loop against E1.
4. Inspect EB for reward hacking, blind spots, and stale tests.
5. Propose evaluator E2 using historical evidence.
6. Validate E2 against regression cases and adversarial solutions.
7. Freeze E2 and start the next inner round.
```

Never compare scores from different evaluator versions without recording the version. Evaluator evolution must not delete or rewrite historical records.

## 6. Recommended first application

Build one local benchmark task with:

- a small deterministic baseline;
- a measurable metric with clear direction;
- a solution package and `solve.sh` entrypoint;
- a trusted evaluator;
- a 10–30 iteration budget;
- two concurrent Proposal Agents;
- artifact and log retention;
- best-so-far result reporting.

Good first tasks include:

- optimizing a numerical algorithm;
- reducing runtime of a small kernel;
- searching training hyperparameters on a tiny dataset;
- improving a deterministic simulation score.

Avoid starting with open-ended drug discovery, large model training, or unrestricted internet research. Those require expensive, domain-specific evaluators and stronger isolation than the Phase 1 local runner provides.

## 7. Definition of done

The implementation is ready for useful experiments when it can:

- submit a task contract;
- generate at least two independent solution packages;
- execute each package in an isolated sandbox;
- produce a task-specific score and validity result;
- append immutable EB records with solution and artifact manifests;
- synthesize inspirations from both best results and failures;
- requeue exploratory work without overwriting prior results;
- return the best reproducible solution and its score;
- stop cleanly on budget, cancellation, or resource exhaustion.

## 8. Source alignment

- [Tencent-Hunyuan/Hyra-results](https://github.com/Tencent-Hunyuan/Hyra-results) — official public research artifacts and task-specific results.
- [Hyra launch page](https://hy.tencent.com/research/hyra) — official project page linked from the Tencent repository.

