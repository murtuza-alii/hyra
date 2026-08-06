from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    state: Path
    solutions: Path
    logs: Path
    sandbox_tmp: Path
    staging: Path

    @classmethod
    def from_root(cls, root: Path) -> "RuntimePaths":
        root = root.resolve()
        return cls(root, root / "state", root / "solutions", root / "logs", root / "sandbox_tmp", root / "runtime" / "staging")

    def ensure(self) -> None:
        for path in (self.state, self.solutions, self.logs, self.sandbox_tmp, self.staging, self.state / "locks"):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class AntigravityConfig:
    agy_path: Path
    brain_dir: Path
    model: str = "pro"
    cli_timeout_seconds: int = 300
    transcript_poll_ms: int = 500
    staging_root: Path = Path("runtime/staging")
    max_context_sessions: int = 1
    max_proposal_sessions: int = 2
    max_evaluator_sessions: int = 1
    allow_host_tools: bool = False

    @classmethod
    def from_environment(cls, paths: RuntimePaths) -> "AntigravityConfig":
        local = Path(os.environ.get("LOCALAPPDATA", "."))
        profile = Path(os.environ.get("USERPROFILE", "."))
        return cls(
            agy_path=Path(os.getenv("AGY_PATH", local / "agy" / "bin" / "agy.exe")),
            brain_dir=Path(os.getenv("BRAIN_DIR", profile / ".gemini" / "antigravity" / "brain")),
            model=os.getenv("AGENT_MODEL", "pro"),
            cli_timeout_seconds=int(os.getenv("ANTIGRAVITY_CLI_TIMEOUT", "300")),
            transcript_poll_ms=int(os.getenv("ANTIGRAVITY_POLL_MS", "500")),
            staging_root=Path(os.getenv("MINI_HYRA_STAGING_ROOT", str(paths.staging))),
            allow_host_tools=os.getenv("ANTIGRAVITY_ALLOW_HOST_TOOLS", "false").lower() == "true",
        )
