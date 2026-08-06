from __future__ import annotations

from dataclasses import dataclass

from .experience_bank import ExperienceBank
from .models import TaskContract


@dataclass(frozen=True)
class Inspiration:
    record_ids: list[str]
    direction: str
    reason: str
    checks: list[str]


class ContextAgent:
    def __init__(self, experience_bank: ExperienceBank) -> None:
        self.experience_bank = experience_bank

    def synthesize(self, task: TaskContract) -> list[Inspiration]:
        records = self.experience_bank.inspirations(task.task_family)
        if not records:
            return [Inspiration([], "establish a valid deterministic baseline", "No historical evidence is available.", task.validity_checks[:3])]
        return [Inspiration([item["run_id"] for item in records], "preserve successful constraints and avoid recent failures", "Historical records are advisory evidence only.", task.validity_checks[:3])]
