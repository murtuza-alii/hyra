from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

from .config import RuntimePaths
from .manifest import PackageValidationError, build_package, validate_id
from .models import SandboxResult


def _result(*, status: str, status_code: str, stderr: str = "", stdout: str = "", exit_code: int | None = None,
            exception_type: str | None = None, exception_message: str | None = None, elapsed: int = 0,
            truncated: bool = False, degraded: bool = False, path: str | None = None) -> SandboxResult:
    return SandboxResult(status=status, status_code=status_code, exit_code=exit_code, stdout=stdout, stderr=stderr,
                         exception_type=exception_type, exception_message=exception_message, execution_time_ms=elapsed,
                         peak_memory_mb=None, cpu_time_ms=None, output_truncated=truncated,
                         isolation_degraded=degraded, sandbox_path=path)


def _strict_isolation_available(allow_network: bool) -> bool:
    # Resource limits and a new process group are useful on POSIX but cannot, by
    # themselves, deny network and host filesystem access. A hardened launcher is
    # deliberately required for strict mode until such a backend is configured.
    return bool(os.environ.get("MINI_HYRA_HARDENED_LAUNCHER")) and not allow_network


def _command(entrypoint: Sequence[str]) -> list[str]:
    if tuple(entrypoint) != ("./solution/solve.sh",):
        raise PackageValidationError("only the canonical ./solution/solve.sh entrypoint is allowed")
    if os.name == "nt":
        launcher = shutil.which("bash")
        if launcher is None:
            raise PackageValidationError("no allow-listed Bash/WSL adapter is available on Windows")
        return [launcher, *entrypoint]
    return ["/bin/sh", *entrypoint]


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
) -> SandboxResult:
    """Execute one validated package; never accepts a host path or shell string."""
    started = time.monotonic()
    try:
        validate_id(task_id, "task_id")
        validate_id(run_id, "run_id")
        package = build_package(solution_files)
        command = _command(entrypoint)
    except PackageValidationError as error:
        return _result(status="FAIL", status_code="SYNTAX_ERROR", stderr=str(error), exception_type=type(error).__name__, exception_message=str(error))
    if timeout_seconds <= 0 or memory_limit_mb < 1 or cpu_time_seconds < 1 or max_output_bytes < 1:
        return _result(status="FAIL", status_code="INTERNAL_ERROR", stderr="invalid sandbox limits")
    if strict_isolation and not _strict_isolation_available(allow_network):
        return _result(status="FAIL", status_code="SECURITY_VIOLATION", stderr="strict isolation is unavailable on this host", degraded=True)

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
        environment = {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "TEMP": str(sandbox / "tmp"), "TMP": str(sandbox / "tmp"), "PATH": os.defpath}
        process = subprocess.Popen(command, cwd=sandbox, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                   preexec_fn=_limit_resources(cpu_time_seconds, memory_limit_mb))
        try:
            raw_stdout, raw_stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate(process)
            raw_stdout, raw_stderr = process.communicate(timeout=0.25)
            elapsed = int((time.monotonic() - started) * 1000)
            return _result(status="FAIL", status_code="TIMEOUT", stdout=raw_stdout.decode("utf-8", "replace"), stderr=raw_stderr.decode("utf-8", "replace"), exit_code=process.returncode, elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None)
        combined = raw_stdout + raw_stderr
        truncated = len(combined) > max_output_bytes
        stdout = raw_stdout[:max_output_bytes].decode("utf-8", "replace")
        remaining = max(0, max_output_bytes - len(raw_stdout))
        stderr = raw_stderr[:remaining].decode("utf-8", "replace")
        elapsed = int((time.monotonic() - started) * 1000)
        if truncated:
            return _result(status="FAIL", status_code="RESOURCE_LIMIT", stdout=stdout, stderr=stderr, exit_code=process.returncode, elapsed=elapsed, truncated=True, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None)
        code = "SUCCESS" if process.returncode == 0 else "RUNTIME_ERROR"
        return _result(status="PASS" if code == "SUCCESS" else "FAIL", status_code=code, stdout=stdout, stderr=stderr, exit_code=process.returncode, elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox else None)
    except Exception as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return _result(status="FAIL", status_code="INTERNAL_ERROR", stderr=str(error), exception_type=type(error).__name__, exception_message=str(error), elapsed=elapsed, degraded=not strict_isolation, path=str(sandbox) if keep_sandbox and sandbox else None)
    finally:
        if temporary is not None and not keep_sandbox:
            temporary.cleanup()
