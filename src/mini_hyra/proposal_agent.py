from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .context_agent import Inspiration
from .models import SolutionPackage, TaskContract


class ProposalAgent(Protocol):
    async def propose(self, *, task: TaskContract, inspiration: Inspiration, staging_dir: Path) -> SolutionPackage: ...
