"""Build records.

A build record is the provenance of one binary.  Without it a crash report is
not reproducible, so the record carries everything needed to produce the same
binary again: compiler identity, exact flags, the commands that ran, the
source commit and the hash of what came out (R-BUILD-02).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import BuildMode, Version

BuildStatus = Literal["success", "failed"]


@dataclass(frozen=True)
class BuildRecord:
    version: Version
    mode: BuildMode
    status: BuildStatus
    compiler: str
    compiler_version: str
    cflags: str
    ldflags: str
    commands: tuple[tuple[str, ...], ...]
    source_revision: str
    source_commit: str
    source_path: str
    build_dir: str
    started_at: str
    duration_s: float
    binary_path: str | None = None
    binary_sha256: str | None = None
    binary_size: int | None = None
    log_ref: str | None = None
    failure_reason: str = ""
    environment: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[Version, BuildMode]:
        return (self.version, self.mode)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"

    @property
    def spec_is_sanitized(self) -> bool:
        """Whether this binary carries a sanitizer runtime.

        Drives two decisions in the execution engine: sanitizer options are
        only injected for these builds, and the address-space limit is lifted
        because a sanitizer reserves far more virtual memory than it uses.
        """
        return self.mode == "sanitized"

    def binary(self) -> Path:
        if self.binary_path is None:
            raise ValueError(f"build {self.key} produced no binary")
        return Path(self.binary_path)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "build_mode": self.mode,
            "status": self.status,
            "compiler": self.compiler,
            "compiler_version": self.compiler_version,
            "cflags": self.cflags,
            "ldflags": self.ldflags,
            "commands": [list(command) for command in self.commands],
            "source_revision": self.source_revision,
            "source_commit": self.source_commit,
            "source_path": self.source_path,
            "build_dir": self.build_dir,
            "started_at": self.started_at,
            "duration_s": round(self.duration_s, 3),
            "binary_path": self.binary_path,
            "binary_sha256": self.binary_sha256,
            "binary_size": self.binary_size,
            "log_ref": self.log_ref,
            "failure_reason": self.failure_reason,
            "environment": dict(self.environment),
        }
