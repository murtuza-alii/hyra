# Mini-Hyra Command-Line Interface

The CLI is the operational interface for Mini-Hyra Phase 1. It is intentionally
separate from proposal generation and evaluation policy: it makes the documented
contracts and evidence visible without granting host execution to untrusted code.

Run it from an installed checkout as `mini-hyra`, or during development as:

```powershell
python -m mini_hyra.main <command>
```

Use `--root <directory>` before the command to select a runtime root. By
default, the current directory is used.

## Workflow

```text
init -> doctor -> task-template -> validate-task -> validate-package
     -> evaluator/orchestrator run -> history -> best
```

The first five commands are safe local operations. An actual research run still
needs a trusted evaluator, a Proposal Agent implementation, and—when proposal
code is untrusted—a strict hardened launcher.

## Commands

### `init`

Creates the ignored runtime directories: `state/`, `solutions/`, `logs/`,
`runtime/staging/`, and `sandbox_tmp/`.

```powershell
mini-hyra init
```

### `doctor`

Shows the runtime location and whether strict execution can be considered for
use. It checks the configured `MINI_HYRA_HARDENED_LAUNCHER`, a Bash adapter, and
the optional Antigravity executable. A launcher being present is only a
prerequisite: its OS policy must be independently verified.

```powershell
mini-hyra doctor
```

### `gpu-status`

Displays NVIDIA GPUs available to the harness, including driver-visible VRAM,
current VRAM use, utilization, and compute capability. It is a read-only
admission check, not a benchmark.

```powershell
mini-hyra gpu-status
mini-hyra gpu-status --json
```

### `task-template` and `validate-task`

`task-template` prints the canonical versioned JSON contract or safely writes it
to a new file. `validate-task` performs strict shape, type, ID, evaluator-hash,
objective, and resource-budget checks.

```powershell
mini-hyra task-template --output task.json
mini-hyra validate-task task.json
```

The contract uses the documented `solution/solve.sh` entrypoint and a frozen
`sha256:<hash>` evaluator identity so scores remain comparable.

### `validate-package`

Checks a proposal directory containing `solution/solve.sh`, rejects symlinks and
unsafe paths, then prints the immutable package hash and file manifest. This is
validation only; it does not execute the package.

```powershell
mini-hyra validate-package .\my-proposal
```

### `run`

Executes the autonomous search and optimization loop for a given task contract.
Connects the Context Agent, Proposal Agent, Sandbox Execution, and Experience Bank.

```powershell
# Run with Antigravity local subscription agent (non-strict sandbox for local micro-benchmarks)
mini-hyra run task.json --agent antigravity --iterations 5 --non-strict

# Run with scripted template agent
mini-hyra run task.json --agent template --iterations 1 --non-strict
```

### `history` and `best`

Read-only Experience Bank views. `history` shows newest records first, and can
be limited to a task or emitted as JSON. `best` selects the best valid score for
one task/evaluator pair in the supplied objective direction.

```powershell
mini-hyra history --task-id algorithm-benchmark --limit 10
mini-hyra history --json
mini-hyra best algorithm-benchmark sha256:<evaluator-hash> --direction minimize
```

`best` never mixes evaluator versions. If no scored valid record exists, it
returns exit status `1`; malformed input and IO/validation errors return `2`.

