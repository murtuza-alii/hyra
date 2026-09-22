from __future__ import annotations

import os
import json
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

from .config import RuntimePaths
from .gpu import GpuInfo, discover_gpus
from .manifest import PackageValidationError, build_package, validate_id
from .models import GpuPolicy, SandboxResult


def _result(*, status: str, status_code: str, stderr: str = "", stdout: str = "", exit_code: int | None = None,
            exception_type: str | None = None, exception_message: str | None = None, elapsed: int = 0,
            truncated: bool = False, degraded: bool = False, path: str | None = None, gpu: GpuInfo | None = None) -> SandboxResult:
    return SandboxResult(status=status, status_code=status_code, exit_code=exit_code, stdout=stdout, stderr=stderr,
                         exception_type=exception_type, exception_message=exception_message, execution_time_ms=elapsed,
                         peak_memory_mb=None, cpu_time_ms=None, output_truncated=truncated,
                         isolation_degraded=degraded, sandbox_path=path,
                         gpu_name=gpu.name if gpu else None, gpu_memory_total_mb=gpu.memory_total_mb if gpu else None,
                         gpu_memory_used_mb=gpu.memory_used_mb if gpu else None,
                         gpu_utilization_percent=gpu.utilization_percent if gpu else None)


def _hardened_launcher() -> str | None:
    """Return a configured launcher only when it is an actual executable file.

    The launcher is deliberately an external, administrator-provisioned security
    boundary (for example, an AppContainer or namespace wrapper).  A Boolean
    environment flag must never be treated as evidence of isolation.
    """
    configured = os.environ.get("MINI_HYRA_HARDENED_LAUNCHER")
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    return str(candidate) if candidate.is_file() else None


def _command(entrypoint: Sequence[str], *, hardened_launcher: str | None) -> list[str]:
    if tuple(entrypoint) != ("./solution/solve.sh",):
        raise PackageValidationError("only the canonical ./solution/solve.sh entrypoint is allowed")
    if os.name == "nt":
        launcher = shutil.which("bash")
        if launcher is None:
            raise PackageValidationError("no allow-listed Bash/WSL adapter is available on Windows")
        command = [launcher, *entrypoint]
    else:
        command = ["/bin/sh", *entrypoint]
    # Hardened launchers implement: launcher -- <command> [args...].
    return [hardened_launcher, "--", *command] if hardened_launcher else command


def _limit_resources(cpu_time_seconds: int, memory_limit_mb: int):
    if os.name == "nt":
        return None
    import resource

    def configure() -> None:
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_time_seconds, cpu_time_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_mb * 1024 * 1024, memory_limit_mb * 1024 * 1024))
    return configure


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_in_sandbox(
    solution_files: Mapping[str, bytes], *, task_id: str, run_id: str,
    paths: RuntimePaths, entrypoint: Sequence[str] = ("./solution/solve.sh",),
    timeout_seconds: float = 5.0, memory_limit_mb: int = 256, cpu_time_seconds: int = 4,
    max_output_bytes: int = 1_048_576, keep_sandbox: bool = False,
    strict_isolation: bool = True, allow_network: bool = False,
    gpu: GpuPolicy | None = None,
) -> SandboxResult:
    """Execute one validated package; never accepts a host path or shell string."""
    started = time.monotonic()
    try:
        validate_id(task_id, "task_id")
        validate_id(run_id, "run_id")
        package = build_package(solution_files)
    except PackageValidationError as error:
        return _result(status="FAIL", status_code="SYNTAX_ERROR", stderr=str(error), exception_type=type(error).__name__, exception_message=str(error))
    if timeout_seconds <= 0 or memory_limit_mb < 1 or cpu_time_seconds < 1 or max_output_bytes < 1:
        return _result(status="FAIL", status_code="INTERNAL_ERROR", stderr="invalid sandbox limits")
    launcher = _hardened_launcher()
    if strict_isolation and launcher is None:
        return _result(status="FAIL", status_code="SECURITY_VIOLATION", stderr="strict isolation requires a configured executable MINI_HYRA_HARDENED_LAUNCHER", degraded=True)
    policy = gpu or GpuPolicy()
    selected_gpu: GpuInfo | None = None
    if policy.enabled:
        selected_gpu = next((item for item in discover_gpus() if item.index == policy.device_index), None)
        if selected_gpu is None:
            return _result(status="FAIL", status_code="GPU_UNAVAILABLE", stderr=f"requested GPU {policy.device_index} is unavailable", degraded=not strict_isolation)
        if selected_gpu.memory_total_mb < policy.min_memory_mb:
            return _result(status="FAIL", status_code="GPU_UNAVAILABLE", stderr=f"GPU {policy.device_index} has {selected_gpu.memory_total_mb} MiB; task requires {policy.min_memory_mb} MiB", degraded=not strict_isolation, gpu=selected_gpu)
    try:
        command = _command(entrypoint, hardened_launcher=launcher if strict_isolation else None)
    except PackageValidationError as error:
        return _result(status="FAIL", status_code="SYNTAX_ERROR", stderr=str(error), exception_type=type(error).__name__, exception_message=str(error))

    paths.ensure()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    sandbox: Path | None = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix=f"mini-hyra-{run_id}-", dir=str(paths.sandbox_tmp))
        sandbox = Path(temporary.name).resolve()
        (sandbox / "tmp").mkdir()
        for relative_path, content in package.files.items():
            target = (sandbox / relative_path).resolve()
            if sandbox not in target.parents:
                raise PackageValidationError("validated package escaped the sandbox")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "TEMP": str(sandbox / "tmp"), "TMP": str(sandbox / "tmp"), "PATH": os.defpath,
                       "MINI_HYRA_GPU_POLICY": json.dumps({"enabled": policy.enabled, "device_index": policy.device_index, "memory_limit_mb": policy.memory_limit_mb, "require_cuda": policy.require_cuda})}
        if policy.enabled:
            environment["CUDA_VISIBLE_DEVICES"] = str(policy.device_index)
            environment["NVIDIA_VISIBLE_DEVICES"] = str(policy.device_index)
        else:
            environment["CUDA_VISIBLE_DEVICES"] = ""
            environment["NVIDIA_VISIBLE_DEVICES"] = "void"
        process = subprocess.Popen(command, cwd=sandbox, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                   preexec_fn=_limit_resources(cpu_time_seconds, memory_limit_mb))
        try:
            raw_stdout, raw_stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate(process)
            raw_stdout, raw_stderr = process.communicate(timeout=0.25)
            elapsed = int((time.monotonic() - started) * 1000)
            return _result(status="FAIL", status_code="TIMEOUT", stdout=raw_stdout.decode("utf-8", "replace"), stderr=raw_stderr.decode("utf-8", "replace"), exit_code=process.returncode, elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None, gpu=selected_gpu)
        combined = raw_stdout + raw_stderr
        truncated = len(combined) > max_output_bytes
        stdout = raw_stdout[:max_output_bytes].decode("utf-8", "replace")
        remaining = max(0, max_output_bytes - len(raw_stdout))
        stderr = raw_stderr[:remaining].decode("utf-8", "replace")
        elapsed = int((time.monotonic() - started) * 1000)
        if truncated:
            return _result(status="FAIL", status_code="RESOURCE_LIMIT", stdout=stdout, stderr=stderr, exit_code=process.returncode, elapsed=elapsed, truncated=True, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None, gpu=selected_gpu)
        code = "SUCCESS" if process.returncode == 0 else "RUNTIME_ERROR"
        final_gpu = next((item for item in discover_gpus() if selected_gpu and item.index == selected_gpu.index), selected_gpu)
        return _result(status="PASS" if code == "SUCCESS" else "FAIL", status_code=code, stdout=stdout, stderr=stderr, exit_code=process.returncode, elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None, gpu=final_gpu)
    except Exception as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return _result(status="FAIL", status_code="INTERNAL_ERROR", stderr=str(error), exception_type=type(error).__name__, exception_message=str(error), elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox and sandbox else None, gpu=selected_gpu)
    finally:
        if temporary is not None and not keep_sandbox:
            temporary.cleanup()
