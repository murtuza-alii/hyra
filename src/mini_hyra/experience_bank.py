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
from .models import ErrorCategory, ExperienceRecord

_lock = threading.RLock()
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/)[^\s]+")
_HASH = re.compile(r"^sha256:[a-f0-9]{64}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")


class _ProcessLock:
    """A small cross-process lock around read/append/replace transactions."""
    def __init__(self, location: Path) -> None:
        self.location = location
        self.handle = None

    def __enter__(self) -> "_ProcessLock":
        self.location.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.location, "a+b")
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if self.handle.tell() == 0 and self.location.stat().st_size == 0:
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: object) -> None:
        assert self.handle is not None
        if os.name == "nt":
            import msvcrt
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


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
            if (not isinstance(record["task_family"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", record["task_family"])
                    or not _HASH.fullmatch(record["solution_version"])
                    or (record["evaluator_version"] != "none" and not _HASH.fullmatch(record["evaluator_version"]))
                    or record["solution_entrypoint"] != "solution/solve.sh" or record["status"] not in {"PASS", "FAIL"}
                    or record["error_category"] not in {item.value for item in ErrorCategory}):
                raise ValueError("invalid experience record contract")
            if (not isinstance(record["iteration"], int) or record["iteration"] < 1
                    or not isinstance(record["execution_time_ms"], int) or record["execution_time_ms"] < 0
                    or len(record["lessons_learned"]) not in range(1, 9) or len(record["inspiration_tags"]) not in range(1, 13)
                    or not all(isinstance(item, str) and 1 <= len(item) <= 500 for item in record["lessons_learned"])
                    or len(set(record["inspiration_tags"])) != len(record["inspiration_tags"])
                    or not all(isinstance(item, str) and _TAG.fullmatch(item) for item in record["inspiration_tags"])):
                raise ValueError("lesson or tag limit violated")
            summary = record["stdout_stderr_summary"]
            if set(summary) != {"stdout_excerpt", "stderr_excerpt", "exit_code"} or not all(isinstance(summary[key], str) and len(summary[key]) <= 4000 for key in ("stdout_excerpt", "stderr_excerpt")):
                raise ValueError("invalid output summary")
            for metric in record["objective_metrics"]:
                if set(metric) != {"name", "value", "direction"} or not re.fullmatch(r"[a-z0-9._-]{1,64}", str(metric["name"])) or not isinstance(metric["value"], (int, float)) or metric["direction"] not in {"minimize", "maximize"}:
                    raise ValueError("invalid objective metric")
            if len(record["objective_metrics"]) > 32 or len(record["artifact_manifest"]) > 256:
                raise ValueError("metric or manifest limit violated")
            for artifact in record["artifact_manifest"]:
                if set(artifact) != {"relative_path", "kind", "sha256", "bytes"} or not re.fullmatch(r"(solution|artifacts)/[^\x00]{1,255}", str(artifact["relative_path"])) or artifact["kind"] not in {"source", "config", "log", "model", "plot", "result", "other"} or not re.fullmatch(r"[a-f0-9]{64}", str(artifact["sha256"])) or not isinstance(artifact["bytes"], int) or artifact["bytes"] < 0:
                    raise ValueError("invalid artifact manifest")
            datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))

    def append(self, record: ExperienceRecord) -> None:
        with _lock, _ProcessLock(self.location.parent / "locks" / "experience_bank.lock"):
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

    def records(self) -> list[dict[str, Any]]:
        """Return a validated snapshot for status interfaces and adapters."""
        document = self._load()
        self._validate(document)
        return list(document["records"])

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
