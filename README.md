# Mini-Hyra

Mini-Hyra is a local Python 3.11+ research harness. It accepts a versioned task contract, evaluates complete `solution/solve.sh` packages, keeps immutable artifacts and an append-only Experience Bank, and returns the best valid result for a single evaluator version.

The initial implementation deliberately separates deterministic evaluation from optional model reasoning. The core does not require an Antigravity installation; the Antigravity adapter is optional and reports an unavailable backend instead of inventing a proposal.

## Safety model

Proposal packages are untrusted. `run_in_sandbox()` defaults to strict isolation and refuses to run when the host cannot provide the required OS isolation. A local development run may opt into degraded isolation explicitly; it is recorded in the result and should not be used for unattended execution.

On Windows, install/configure a low-privilege Job Object/AppContainer runner or WSL before executing shell packages. The current host has neither WSL nor an allow-listed POSIX shell, so this checkout can validate packages and run deterministic unit tests, but cannot safely execute `solve.sh` packages here.

## Layout

`src/mini_hyra/` contains contracts, staging/manifest validation, sandbox execution, evaluation, Experience Bank, agent integration, and orchestration. Runtime state is intentionally excluded from source control.

Run tests with a Python 3.11+ environment:

```powershell
python -m pytest
```
