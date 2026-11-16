"""Sandbox Manager — module 4 of the architecture.

Selects a backend, verifies up front that it actually works here, and runs
every target execution through it.
"""

from __future__ import annotations

import dataclasses
import logging

from ..config import SandboxSpec
from ..errors import SandboxUnavailable
from .base import ProbeReport, SandboxBackend, SandboxRequest, SandboxResult
from .bubblewrap import BubblewrapSandboxBackend
from .subprocess_backend import SubprocessSandboxBackend

log = logging.getLogger(__name__)

_BACKENDS: dict[str, type] = {
    BubblewrapSandboxBackend.name: BubblewrapSandboxBackend,
    SubprocessSandboxBackend.name: SubprocessSandboxBackend,
}


class SandboxManager:
    """Owns backend selection and the pre-flight capability check."""

    def __init__(self, spec: SandboxSpec) -> None:
        self.spec = spec
        backend_class = _BACKENDS.get(spec.backend)
        if backend_class is None:  # pragma: no cover - schema rejects this first
            raise SandboxUnavailable(f"unknown sandbox backend '{spec.backend}'")
        self.backend: SandboxBackend = backend_class()
        self._probe: ProbeReport | None = None

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def probe(self, *, refresh: bool = False) -> ProbeReport:
        """Run (and cache) the backend capability probe."""
        if self._probe is None or refresh:
            self._probe = self.backend.probe()
            for check, outcome in self._probe.checks.items():
                log.debug("sandbox probe: %-22s %s", check, outcome)
        return self._probe

    def ensure_available(self) -> ProbeReport:
        """Fail loudly rather than run a vulnerable binary unprotected.

        A missing sandbox is a configuration problem (exit code 30), never a
        reason to downgrade to unisolated execution (R-SBX-07).
        """
        report = self.probe()
        if not report.available:
            raise SandboxUnavailable(
                f"sandbox backend '{report.backend}' is unavailable: {report.reason}",
                remedy=report.remedy,
            )
        if self.backend.name == SubprocessSandboxBackend.name:
            if not self.spec.unsafe_ack:  # pragma: no cover - loader rejects first
                raise SandboxUnavailable(
                    "the 'subprocess' backend provides no isolation and was not "
                    "explicitly acknowledged",
                    remedy="set sandbox.unsafe_ack: true, or use bubblewrap",
                )
            log.warning(
                "running target executions WITHOUT isolation; results are "
                "labelled sandbox_backend='subprocess' in the report"
            )
        return report

    def run(self, request: SandboxRequest) -> SandboxResult:
        """Execute one request under the selected backend."""
        self.ensure_available()
        if self.spec.network and not request.network:
            request = dataclasses.replace(request, network=True)
        return self.backend.run(request)
