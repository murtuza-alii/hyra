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
    """Async wrapper around local agy.exe; polls local brain transcripts for response."""
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

        initial_line_count = 0
        transcript_file: Path | None = None

        if conversation_id:
            transcript_full = self.config.brain_dir / conversation_id / ".system_generated" / "logs" / "transcript_full.jsonl"
            transcript_compact = self.config.brain_dir / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
            transcript_file = transcript_full if transcript_full.exists() else (transcript_compact if transcript_compact.exists() else transcript_full)
            if transcript_file.exists():
                try:
                    initial_line_count = len(transcript_file.read_text(encoding="utf-8").splitlines())
                except OSError:
                    initial_line_count = 0

        if not conversation_id:
            command = [
                str(self.config.agy_path), "agentapi", "new-conversation",
                f"--model={self.config.model}", f"--title=Mini-Hyra [{role}]", message
            ]
        else:
            command = [
                str(self.config.agy_path), "agentapi", "send-message",
                conversation_id, message
            ]

        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=self.config.cli_timeout_seconds, shell=False
            )
            elapsed = int((time.monotonic() - started) * 1000)
            if completed.returncode != 0:
                err = completed.stderr.strip() or completed.stdout.strip()
                return AgentResponse(False, completed.stdout[-4000:], conversation_id, role, None, 0, elapsed, err)

            try:
                payload = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {}
            except json.JSONDecodeError:
                payload = {}

            if not conversation_id:
                new_id = payload.get("response", {}).get("newConversation", {}).get("conversationId")
                if not new_id:
                    new_id = payload.get("conversation_id")
                if not new_id:
                    return AgentResponse(False, completed.stdout, None, role, None, 0, elapsed, "Failed to extract conversationId from agy response")
                conversation_id = str(new_id)
                initial_line_count = 0

            transcript_full = self.config.brain_dir / conversation_id / ".system_generated" / "logs" / "transcript_full.jsonl"
            transcript_compact = self.config.brain_dir / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"

            poll_interval = max(0.1, self.config.transcript_poll_ms / 1000.0)
            tool_calls_observed = 0

            while (time.monotonic() - started) < self.config.cli_timeout_seconds:
                active_transcript = transcript_full if transcript_full.exists() else (transcript_compact if transcript_compact.exists() else None)
                if active_transcript and active_transcript.exists():
                    try:
                        lines = active_transcript.read_text(encoding="utf-8").splitlines()
                        for i in range(initial_line_count, len(lines)):
                            line = lines[i].strip()
                            if not line:
                                continue
                            try:
                                step = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            if step.get("tool_calls"):
                                tool_calls_observed += len(step["tool_calls"])

                            if (
                                step.get("source") == "MODEL"
                                and step.get("type") == "PLANNER_RESPONSE"
                                and step.get("status") == "DONE"
                                and not step.get("tool_calls")
                            ):
                                content = step.get("content", "")
                                elapsed = int((time.monotonic() - started) * 1000)
                                return AgentResponse(
                                    True, content, conversation_id, role,
                                    str(active_transcript), tool_calls_observed, elapsed, None
                                )
                    except OSError:
                        pass

                time.sleep(poll_interval)

            elapsed = int((time.monotonic() - started) * 1000)
            return AgentResponse(
                False, "", conversation_id, role,
                str(transcript_full) if transcript_full.exists() else None,
                tool_calls_observed, elapsed, "Execution timeout exceeded waiting for agent response"
            )

        except (OSError, subprocess.TimeoutExpired) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            return AgentResponse(False, "", conversation_id, role, None, 0, elapsed, str(error))

    async def reset_session(self, conversation_id: str) -> None:
        pass

