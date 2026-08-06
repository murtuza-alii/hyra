from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class Session:
    conversation_id: str
    role: str
    transcript_path: str | None


class SessionPool:
    """Role-separated session registry; proposal workers never share sessions."""
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def get(self, worker_key: str, role: str) -> Session | None:
        async with self._lock:
            session = self._sessions.get(worker_key)
            return session if session is None or session.role == role else None

    async def put(self, worker_key: str, session: Session) -> None:
        async with self._lock:
            existing = self._sessions.get(worker_key)
            if existing and existing.role != session.role:
                raise ValueError("session role collision")
            self._sessions[worker_key] = session

    async def retire(self, worker_key: str) -> Session | None:
        async with self._lock:
            return self._sessions.pop(worker_key, None)
