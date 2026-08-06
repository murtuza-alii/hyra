from __future__ import annotations

import json
import shutil
from pathlib import Path

from .config import RuntimePaths
from .manifest import PackageValidationError, build_package, validate_id
from .models import SolutionPackage


class StagingManager:
    """Owns the model-to-harness handoff; staging is never an execution path."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    def stage_path(self, task_id: str, run_id: str) -> Path:
        validate_id(task_id, "task_id")
        validate_id(run_id, "run_id")
        return self.paths.staging / task_id / run_id

    def load_staged_package(self, task_id: str, run_id: str) -> SolutionPackage:
        root = self.stage_path(task_id, run_id).resolve()
        solution_root = root / "solution"
        if not solution_root.is_dir():
            raise PackageValidationError("staging directory does not contain solution/")
        files: dict[str, bytes] = {}
        for item in solution_root.rglob("*"):
            if item.is_symlink():
                raise PackageValidationError("symlinks are not permitted in staged packages")
            if item.is_file():
                files[item.relative_to(root).as_posix()] = item.read_bytes()
        return build_package(files)

    def persist_immutable(self, task_id: str, run_id: str, package: SolutionPackage) -> Path:
        target = self.paths.solutions / task_id / run_id
        if target.exists():
            raise FileExistsError(f"immutable solution already exists: {target}")
        target.mkdir(parents=True)
        try:
            for relative_path, content in package.files.items():
                destination = target / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            (target / "manifest.json").write_text(json.dumps([
                {"relative_path": item.relative_path, "kind": item.kind, "sha256": item.sha256, "bytes": item.bytes}
                for item in package.manifest
            ], indent=2), encoding="utf-8")
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return target
