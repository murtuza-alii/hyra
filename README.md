# Mini-Hyra

Mini-Hyra is a local Python 3.11+ research harness. It accepts a versioned task contract, evaluates complete `solution/solve.sh` packages, keeps immutable artifacts and an append-only Experience Bank, and returns the best valid result for a single evaluator version.

The initial implementation deliberately separates deterministic evaluation from optional model reasoning. The core does not require an Antigravity installation; the Antigravity adapter is optional and reports an unavailable backend instead of inventing a proposal.

## Safety model

Proposal packages are untrusted. `run_in_sandbox()` defaults to strict isolation and refuses to run when the host cannot provide the required OS isolation. A local development run may opt into degraded isolation explicitly; it is recorded in the result and should not be used for unattended execution.

On Windows, install/configure a low-privilege Job Object/AppContainer runner or WSL before executing shell packages. The current host has neither WSL nor an allow-listed POSIX shell, so this checkout can validate packages and run deterministic unit tests, but cannot safely execute `solve.sh` packages here.

## Layout

`src/mini_hyra/` contains contracts, staging/manifest validation, sandbox execution, evaluation, Experience Bank, agent integration, and orchestration. Runtime state is intentionally excluded from source control.

## Command-line interface

The command-line interface is the operator surface for Phase 1. It manages
contracts, validates solution packages before they reach a sandbox, reports the
strict-execution prerequisite, and reads the Experience Bank without editing it.

```powershell
mini-hyra init
mini-hyra doctor
mini-hyra gpu-status
mini-hyra task-template --output task.json
mini-hyra validate-task task.json
mini-hyra validate-package .\my-proposal
mini-hyra history --task-id algorithm-benchmark
mini-hyra best algorithm-benchmark sha256:<evaluator-hash> --direction minimize
```

See [the CLI guide](docs/08_command_line_interface.md) for the complete command
reference and workflow.

GPU-capable tasks are documented in [the GPU guide](docs/09_gpu_execution.md).
For the projects already on E:, use [the existing-project rollout guide](docs/10_existing_projects_gpu_rollout.md).

Install the project with its test tools, then run tests with a Python 3.11+ environment:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

The test configuration uses a repository-local temporary directory so it also
works in Windows environments where the global temporary folder is restricted.

## Strict execution prerequisite

Strict execution is intentionally unavailable until an administrator provides a
real OS-isolation wrapper. Set `MINI_HYRA_HARDENED_LAUNCHER` to the absolute path
of an executable that implements `launcher -- <command> [args...]` and applies
the required filesystem, process, and network policy. Merely setting a Boolean
flag does not enable execution. Without that launcher, Mini-Hyra can validate
packages and test deterministic components, but rejects untrusted execution in
strict mode. Development-only runs may set `strict_isolation=False`; every such
result is marked `isolation_degraded=true` and must not be used unattended.
