"""Execution results.

One record per (test case, version, build mode).  It holds raw observation
only — no interpretation.  Deciding whether a result represents a memory
error, a timeout or ordinary rejection of invalid input is the crash
analyzer's job, and keeping the two apart is what stops an exit code from
quietly being treated as a vulnerability (R-DYN-14).
"""

from __future__ import annotations

import signal as signal_module
from dataclasses import dataclass, field

from ..config import BuildMode, Version


@dataclass(frozen=True)
class ExecutionResult:
    test_id: str
    version: Version
    build_mode: BuildMode

    exit_code: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    duration_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    signal_inferred: bool

    #: Everything needed to run this exact execution again.
    argv: tuple[str, ...]
    env: dict[str, str]
    input_sha256: str
    input_size: int
    binary_sha256: str
    binary_path: str
    sandbox_backend: str
    sandbox_command: tuple[str, ...]
    rlimits: dict[str, str]
    timeout_s: float

    stdout_ref: str = ""
    stderr_ref: str = ""
    meta_ref: str = ""
    launch_error: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, Version, BuildMode]:
        return (self.test_id, self.version, self.build_mode)

    @property
    def signal_name(self) -> str | None:
        if self.signal is None:
            return None
        try:
            return signal_module.Signals(self.signal).name
        except ValueError:  # pragma: no cover - unknown signal number
            return f"SIG{self.signal}"

    @property
    def terminated_by_signal(self) -> bool:
        return self.signal is not None

    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")

    def to_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "version": self.version,
            "build_mode": self.build_mode,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "signal_name": self.signal_name,
            "signal_inferred": self.signal_inferred,
            "duration_s": round(self.duration_s, 6),
            "timed_out": self.timed_out,
            "timeout_s": self.timeout_s,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "stdout_ref": self.stdout_ref,
            "stderr_ref": self.stderr_ref,
            "argv": list(self.argv),
            "env": dict(self.env),
            "input_sha256": self.input_sha256,
            "input_size": self.input_size,
            "binary_sha256": self.binary_sha256,
            "binary_path": self.binary_path,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_command": list(self.sandbox_command),
            "rlimits": dict(self.rlimits),
            "launch_error": self.launch_error,
            "extra": dict(self.extra),
        }
