# Mini-Hyra Sandbox Execution Specification

## 1. Isolation strategy

Proposal code is untrusted. The canonical input is a complete package with this layout:

```text
solution/
├── solve.sh                 # required entrypoint
├── source files
├── configuration files
└── local assets
```

For every run, create an ephemeral directory with Python's `tempfile.TemporaryDirectory`, copy only validated relative package paths into it, and launch the entrypoint with `subprocess` using `shell=False`.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

with TemporaryDirectory(prefix=f"mini-hyra-{run_id}-", dir=str(sandbox_root)) as raw:
    sandbox_dir = Path(raw)
    write_validated_solution_files(sandbox_dir / "solution", solution_files)
    run_entrypoint(sandbox_dir, ["./solution/solve.sh"])
```

The parent verifies that every resolved path stays below the sandbox root and rejects symlinks in the input package. The execution copy is deleted after the run; the immutable source package and manifest remain under `solutions/<task_id>/<run_id>/`.

`cwd` isolation alone is not a complete security boundary. POSIX deployments should add process groups, `resource.setrlimit`, and an OS policy such as a private mount namespace or restricted account. Windows deployments should use a Job Object, process-group cleanup, ACL-restricted directories, and a low-privilege child account or AppContainer policy. Strict mode refuses to execute when required isolation is unavailable.

### 1.1 Strict launcher contract

Strict mode requires `MINI_HYRA_HARDENED_LAUNCHER` to name an existing executable.
Mini-Hyra invokes it as:

```text
<launcher> -- <allow-listed shell> ./solution/solve.sh
```

The launcher—not a Boolean environment flag—is responsible for enforcing the
filesystem, network, child-process, and low-privilege policy. An unset or
nonexistent launcher causes a `SECURITY_VIOLATION` result before proposal code
runs. This is deliberately fail-closed. Development-only callers may request
`strict_isolation=False`; their result is marked `isolation_degraded=true` and
is unsuitable for unattended execution.

### 1.2 GPU tasks

A task may opt into one NVIDIA GPU through its `GpuPolicy`. Before launch,
Mini-Hyra probes `nvidia-smi` and rejects a GPU task with `GPU_UNAVAILABLE` when
the selected device is absent or has less than the declared minimum VRAM. It
records the selected GPU's name, total VRAM, current VRAM use, and current
utilization in `SandboxResult` as admission/exit telemetry.

Mini-Hyra passes `CUDA_VISIBLE_DEVICES`, `NVIDIA_VISIBLE_DEVICES`, and a bounded
`MINI_HYRA_GPU_POLICY` JSON value to the launcher. Those values communicate the
task's intent; they are not isolation. A strict launcher must enforce device
selection and the VRAM cap using the host's supported mechanism. CPU-only tasks
receive an explicit no-GPU environment.

## 2. Process invocation and environment

```python
command = [allowlisted_launcher, *entrypoint]
completed = subprocess.run(
    command,
    cwd=sandbox_dir,
    env={
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PATH": str(allowlisted_bin_dir),
        "TEMP": str(sandbox_dir / "tmp"),
        "TMP": str(sandbox_dir / "tmp"),
    },
    stdin=subprocess.DEVNULL,
    capture_output=True,
    text=False,
    timeout=timeout_seconds,
    check=False,
    shell=False,
)
```

Do not inherit API keys, credentials, proxy variables, user profile paths, or the parent environment. Network access is denied unless the task contract explicitly permits it through an OS policy.

## 3. Guardrails and task profiles

| Guardrail | Default micro-task profile | Enforcement | Failure |
|---|---:|---|---|
| Wall-clock execution | 5 seconds | subprocess timeout and process-tree kill | `TIMEOUT` |
| CPU time | 4 seconds | POSIX limit or Windows Job Object | `RESOURCE_LIMIT` |
| Peak memory | 256 MiB | POSIX limit where supported or Windows Job Object | `RESOURCE_LIMIT` |
| Child processes | 0 by default | process policy and cleanup | `SECURITY_VIOLATION` |
| Combined stdout/stderr | 1 MiB | bounded capture | `RESOURCE_LIMIT` |
| Package size | 256 KiB default | pre-launch validation | `RESOURCE_LIMIT` |
| Network | disabled | OS policy | `SECURITY_VIOLATION` |
| Host filesystem | sandbox root only | ACL/namespace plus path checks | `SECURITY_VIOLATION` |

Research tasks may define larger limits in their `TaskContract`; the 5-second limit is not a universal Hyra limit. Every result records the active policy and whether isolation was degraded.

## 4. Exact runner interface

The module is `src/mini_hyra/sandbox_runner.py`.

```python
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

StatusCode = Literal[
    "SUCCESS", "SYNTAX_ERROR", "TEST_FAILURE", "RUNTIME_ERROR", "TIMEOUT",
    "RESOURCE_LIMIT", "SECURITY_VIOLATION", "INTERNAL_ERROR",
]

class SandboxResult(TypedDict):
    status: Literal["PASS", "FAIL"]
    status_code: StatusCode
    exit_code: int | None
    stdout: str
    stderr: str
    exception_type: str | None
    exception_message: str | None
    execution_time_ms: int
    peak_memory_mb: int | None
    cpu_time_ms: int | None
    output_truncated: bool
    isolation_degraded: bool
    sandbox_path: str | None

def run_in_sandbox(
    solution_files: Mapping[str, bytes],
    *,
    task_id: str,
    run_id: str,
    entrypoint: Sequence[str] = ("./solution/solve.sh",),
    timeout_seconds: float = 5.0,
    memory_limit_mb: int = 256,
    cpu_time_seconds: int = 4,
    max_output_bytes: int = 1_048_576,
    keep_sandbox: bool = False,
    strict_isolation: bool = True,
) -> SandboxResult:
    """Run one solution package and return a JSON-serializable result."""
```

### 4.1 Input contracts

| Argument | Contract |
|---|---|
| `solution_files` | relative POSIX paths to UTF-8 or binary contents; no absolute paths, `..`, symlinks, or files above the package limit |
| `task_id`, `run_id` | non-empty IDs matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` |
| `entrypoint` | argument array only; executable must be allow-listed; default is `./solution/solve.sh` |
| `timeout_seconds` | `0 < value <= task maximum`; default 5.0 |
| `memory_limit_mb` | `1..task maximum`; default 256 |
| `cpu_time_seconds` | `1..task maximum`; default 4 |
| `max_output_bytes` | `1..1,048,576` by default |
| `strict_isolation` | true for unattended evaluation; refuses degraded execution |

`candidate.py` remains supported only as a compatibility adapter that constructs a minimal `solution/solve.sh` package. The primary API never accepts a host path or shell command string.

### 4.2 Return dictionary and exception mapping

Every return path contains every `SandboxResult` key. Output is UTF-8 with invalid bytes replaced and capped at `max_output_bytes` combined.

| Observation | Return mapping |
|---|---|
| clean entrypoint and valid evaluator result | `PASS`, `SUCCESS` |
| non-zero static/preflight result | `FAIL`, `SYNTAX_ERROR` |
| non-zero task result | `FAIL`, `TEST_FAILURE` or `RUNTIME_ERROR` |
| `subprocess.TimeoutExpired` | `FAIL`, `TIMEOUT`, terminate process tree |
| resource limit signal | `FAIL`, `RESOURCE_LIMIT` |
| forbidden path, network, import, or process | `FAIL`, `SECURITY_VIOLATION` |
| parent-side unexpected exception | `FAIL`, `INTERNAL_ERROR` |

On timeout, kill the whole process group or Job Object, wait at most 250 ms for cleanup, close pipes, and record the timeout evidence. The `finally` block must always release resources and let `TemporaryDirectory` remove the execution copy unless `keep_sandbox=true`.

## 5. Static and functional phases

The Grader first validates package layout and entrypoint policy. It then invokes `run_in_sandbox` for the solution. A static/preflight failure skips functional evaluation. A successful run is passed to the task evaluator, which determines validity and objective score. The evaluator, not the sandbox runner, decides whether the result is best-so-far.

## 6. Logging and reproducibility

Store the full package manifest, stdout, stderr, timing, evaluator version, active resource policy, objective result, and artifact hashes under `logs/runs/<task_id>/<run_id>/` and `solutions/<task_id>/<run_id>/`. Store only bounded excerpts and manifest metadata in EB. Never log the parent environment, secrets, or arbitrary host paths.

