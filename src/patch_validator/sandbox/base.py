"""Sandbox contract shared by every backend."""

from __future__ import annotations

import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SandboxRequest:
    """One isolated execution of a target binary."""

    argv: tuple[str, ...]
    #: Host directory bound read-write as the process working directory.
    workdir: Path
    #: Host paths exposed read-only, in addition to the system defaults.
    ro_binds: tuple[Path, ...] = ()
    stdin_data: bytes | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 10.0
    cpu_s: int = 10
    memory_mb: int = 1024
    max_processes: int = 64
    max_file_size_mb: int = 64
    max_output_bytes: int = 1 << 20
    network: bool = False
    #: Sanitizer runtimes reserve a huge virtual address range, so RLIMIT_AS
    #: makes them abort during start-up.  The execution engine clears this for
    #: sanitized builds and bounds memory through the sanitizer instead.
    apply_address_space_limit: bool = True


@dataclass(frozen=True)
class SandboxResult:
    """Everything observed about one isolated execution."""

    argv: tuple[str, ...]
    exit_code: int | None
    signal: int | None
    stdout: bytes
    stderr: bytes
    duration_s: float
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool
    backend: str
    #: The exact command line used to launch the sandbox, for reproduction.
    sandbox_command: tuple[str, ...]
    rlimits: dict[str, str]

    @property
    def signal_name(self) -> str | None:
        if self.signal is None:
            return None
        try:
            return signal.Signals(self.signal).name
        except ValueError:
            return f"SIG{self.signal}"

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "signal": self.signal,
            "signal_name": self.signal_name,
            "duration_s": round(self.duration_s, 6),
            "timed_out": self.timed_out,
            "stdout_truncated": self.stdout_truncated,
            "stderr_truncated": self.stderr_truncated,
            "backend": self.backend,
            "sandbox_command": list(self.sandbox_command),
            "rlimits": dict(self.rlimits),
        }


@dataclass(frozen=True)
class ProbeReport:
    """Result of checking whether a backend can run here."""

    backend: str
    available: bool
    #: Individual capability checks, e.g. {"user_namespaces": "ok"}.
    checks: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    remedy: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "available": self.available,
            "checks": dict(self.checks),
            "reason": self.reason,
            "remedy": self.remedy,
        }


@runtime_checkable
class SandboxBackend(Protocol):
    """A way to run an untrusted binary under isolation and resource limits."""

    name: str

    def probe(self) -> ProbeReport:
        """Report whether this backend can run in the current environment."""

    def run(self, request: SandboxRequest) -> SandboxResult:
        """Execute ``request`` and return what was observed."""
