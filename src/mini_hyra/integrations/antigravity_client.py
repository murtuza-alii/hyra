from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config import AntigravityConfig


@dataclass(frozen=True)
class AgentResponse:
    success: bool
    content: str
    conversation_id: str | None
    session_role: Literal["context", "proposal", "evaluator"]
    transcript_path: str | None
    tool_calls_observed: int
    elapsed_ms: int
    error: str | None


class AntigravityClient:
    """Async wrapper around local agy.exe; no host tools are granted by this client."""
    def __init__(self, config: AntigravityConfig) -> None:
        self.config = config

    async def send_message(self, *, role: Literal["context", "proposal", "evaluator"], message: str,
                           conversation_id: str | None = None, staging_dir: Path | None = None) -> AgentResponse:
        if role == "proposal" and (staging_dir is None or not staging_dir.resolve().is_relative_to(self.config.staging_root.resolve())):
            return AgentResponse(False, "", conversation_id, role, None, 0, 0, "proposal staging directory is outside the configured staging root")
        return await asyncio.to_thread(self._send_sync, role, message, conversation_id)

    def _send_sync(self, role: str, message: str, conversation_id: str | None) -> AgentResponse:
        started = time.monotonic()
        if not self.config.agy_path.is_file():
            return AgentResponse(False, "", conversation_id, role, None, 0, 0, f"agy.exe is unavailable at {self.config.agy_path}")
        command = [str(self.config.agy_path), "agentapi", "send-message" if conversation_id else "new-conversation"]
        if conversation_id:
            command.extend(["--conversation-id", conversation_id])
        command.extend(["--message", message, "--model", self.config.model])
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=self.config.cli_timeout_seconds, shell=False)
            elapsed = int((time.monotonic() - started) * 1000)
            if completed.returncode:
                return AgentResponse(False, completed.stdout[-4000:], conversation_id, role, None, 0, elapsed, completed.stderr[-1000:])
            payload = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {}
            return AgentResponse(True, str(payload.get("content", completed.stdout)), str(payload.get("conversation_id", conversation_id)) if payload.get("conversation_id", conversation_id) else None, role, payload.get("transcript_path"), int(payload.get("tool_calls_observed", 0)), elapsed, None)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            return AgentResponse(False, "", conversation_id, role, None, 0, elapsed, str(error))

    async def reset_session(self, conversation_id: str) -> None:
        if self.config.agy_path.is_file():
            await asyncio.to_thread(subprocess.run, [str(self.config.agy_path), "agentapi", "reset-session", "--conversation-id", conversation_id], capture_output=True, check=False, shell=False)
