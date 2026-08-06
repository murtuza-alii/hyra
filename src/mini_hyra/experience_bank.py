from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import validate_id
from .models import ExperienceRecord

_lock = threading.RLock()
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/)[^\s]+")


class ExperienceBank:
    """Append-only JSON storage with full-document validation and atomic replacement."""

    def __init__(self, location: Path) -> None:
        self.location = location

    def _load(self) -> dict[str, Any]:
        if not self.location.exists():
            return {"schema_version": "1.1", "records": []}
        return json.loads(self.location.read_text(encoding="utf-8"))

    @staticmethod
    def _validate(document: dict[str, Any]) -> None:
        if set(document) != {"schema_version", "records"} or document["schema_version"] != "1.1" or not isinstance(document["records"], list):
            raise ValueError("experience bank does not match schema version 1.1")
        for record in document["records"]:
            required = {"run_id", "task_id", "task_family", "iteration", "solution_version", "evaluator_version", "solution_entrypoint", "status", "error_category", "execution_time_ms", "stdout_stderr_summary", "objective_metrics", "is_best_so_far", "artifact_manifest", "lessons_learned", "inspiration_tags", "created_at"}
            if set(record) != required:
                raise ValueError("experience record fields do not match the strict schema")
            validate_id(record["run_id"], "run_id")
            validate_id(record["task_id"], "task_id")
            if record["solution_entrypoint"] != "solution/solve.sh" or record["status"] not in {"PASS", "FAIL"}:
                raise ValueError("invalid experience record contract")
            if len(record["lessons_learned"]) not in range(1, 9) or len(record["inspiration_tags"]) not in range(1, 13):
                raise ValueError("lesson or tag limit violated")

    def append(self, record: ExperienceRecord) -> None:
        with _lock:
            document = self._load()
            self._validate(document)
            if any(existing["run_id"] == record.run_id for existing in document["records"]):
                raise ValueError(f"run_id already exists: {record.run_id}")
            document["records"].append(record.to_dict())
            self._validate(document)
            self.location.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.location.parent, delete=False) as handle:
                json.dump(document, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            os.replace(temporary, self.location)

    def best_score(self, task_id: str, evaluator_version: str, direction: str) -> float | None:
        records = [item for item in self._load()["records"] if item["task_id"] == task_id and item["evaluator_version"] == evaluator_version and item["status"] == "PASS" and item["objective_metrics"]]
        scores = [float(item["objective_metrics"][0]["value"]) for item in records]
        return (max(scores) if direction == "maximize" else min(scores)) if scores else None

    @staticmethod
    def sanitize(text: str) -> str:
        return _ABS_PATH.sub("<path>", _CONTROL.sub(" ", text)).replace("[MINI-HYRA", "[REDACTED").strip()[:500]

    def inspirations(self, task_family: str, limit: int = 6) -> list[dict[str, Any]]:
        candidates = [item for item in self._load()["records"] if item["task_family"] == task_family][-40:]
        successes = [item for item in candidates if item["status"] == "PASS"]
        failures = [item for item in candidates if item["status"] == "FAIL"]
        selected = (successes[-3:] + failures[-3:])[-limit:]
        return [{"run_id": item["run_id"], "status": item["status"], "lessons": [self.sanitize(lesson) for lesson in item["lessons_learned"][:2]], "artifact_paths": [entry["relative_path"] for entry in item["artifact_manifest"][:3]]} for item in selected]

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
