from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Mapping

from .models import ArtifactManifestItem, SolutionPackage

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PACKAGE_BYTES = 256 * 1024


class PackageValidationError(ValueError):
    pass


def validate_id(value: str, label: str) -> None:
    if not _ID.fullmatch(value):
        raise PackageValidationError(f"{label} must match {_ID.pattern}")


def validate_relative_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if not path or candidate.is_absolute() or "\\" in path or ".." in candidate.parts or "." in candidate.parts:
        raise PackageValidationError(f"unsafe package path: {path!r}")
    if candidate.parts[0] not in {"solution", "artifacts"}:
        raise PackageValidationError("package paths must begin with solution/ or artifacts/")
    return candidate


def build_package(files: Mapping[str, bytes], *, max_package_bytes: int = _MAX_PACKAGE_BYTES) -> SolutionPackage:
    total = 0
    manifest: list[ArtifactManifestItem] = []
    normalized: dict[str, bytes] = {}
    for relative_path, content in files.items():
        validate_relative_path(relative_path)
        if not isinstance(content, bytes):
            raise PackageValidationError(f"{relative_path} must contain bytes")
        total += len(content)
        if total > max_package_bytes:
            raise PackageValidationError("package exceeds configured size limit")
        normalized[relative_path] = content
        manifest.append(ArtifactManifestItem(
            relative_path=relative_path,
            kind="source" if relative_path.startswith("solution/") else "other",
            sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
        ))
    if "solution/solve.sh" not in normalized:
        raise PackageValidationError("solution/solve.sh is required")
    return SolutionPackage(files=normalized, manifest=tuple(sorted(manifest, key=lambda item: item.relative_path)))


def solution_hash(package: SolutionPackage) -> str:
    digest = hashlib.sha256()
    for item in package.manifest:
        digest.update(item.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.sha256.encode("ascii"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()
