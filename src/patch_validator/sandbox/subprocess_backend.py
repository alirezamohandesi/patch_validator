"""Unisolated fallback backend.

This backend provides resource limits and process-group cleanup but **no
isolation**: the target can read and write the host filesystem with the
privileges of the calling user and can reach the network.

It exists only so the tool remains usable while debugging on a machine where
namespaces are unavailable, and it refuses to be selected implicitly: the
configuration must acknowledge it (``sandbox.unsafe_ack: true``), and every
report produced with it records the backend name so no result can quietly be
mistaken for an isolated one (ADR-003).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import ProbeReport, SandboxRequest, SandboxResult
from .runner import execute

log = logging.getLogger(__name__)


class SubprocessSandboxBackend:
    """Resource-limited, *unisolated* execution."""

    name = "subprocess"

    def probe(self) -> ProbeReport:
        return ProbeReport(
            backend=self.name,
            available=True,
            checks={
                "isolation": "none",
                "filesystem": "host filesystem is fully visible",
                "network": "host network is reachable",
                "resource_limits": "rlimits only",
            },
            reason="",
            remedy=(
                "this backend provides no isolation; prefer bubblewrap for "
                "anything other than local debugging"
            ),
        )

    def sandbox_path(self, host_workdir: Path) -> str:
        """Without a mount namespace the host path is the only path."""
        return str(host_workdir)

    def run(self, request: SandboxRequest) -> SandboxResult:
        log.warning(
            "executing %s WITHOUT isolation (subprocess backend)",
            Path(request.argv[0]).name,
        )
        env = dict(request.env)
        env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
        return execute(
            list(request.argv),
            request,
            backend=self.name,
            env=env,
            nproc=_headroom_nproc(request.max_processes),
        )


def _headroom_nproc(allowance: int) -> int | None:
    """Translate a per-target process allowance into a per-uid RLIMIT_NPROC.

    Without a user namespace the limit is counted against every process the
    calling user already owns, so it has to be set relative to current usage.
    That makes it a fork-bomb brake rather than a precise ceiling, which is
    one more reason this backend is not the default.
    """
    try:
        current = len(
            [
                entry
                for entry in Path("/proc").iterdir()
                if entry.name.isdigit() and entry.stat().st_uid == os.getuid()
            ]
        )
    except OSError:  # pragma: no cover - /proc is always present on Linux
        return None
    return current + allowance
