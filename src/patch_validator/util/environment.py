"""Runtime environment capture.

Recorded once per run and embedded in every reproducer bundle.  A crash that
cannot be tied to the environment it happened in is not reproducible, and the
specification's amendment asks specifically for the container image digest and
the sandbox backend alongside the usual build metadata.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

#: Environment variable a CI job can set to record exactly which image it ran.
IMAGE_DIGEST_VAR = "PATCH_VALIDATOR_IMAGE_DIGEST"

_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")


def capture() -> dict[str, Any]:
    """Snapshot of the machine and container this run executes on."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "container": container_identity(),
        "image_digest": os.environ.get(IMAGE_DIGEST_VAR, ""),
        "tools": tool_versions(),
    }


def container_identity() -> dict[str, str]:
    """Best-effort identification of the container this process runs in."""
    identity: dict[str, str] = {"detected": "false"}

    if Path("/.dockerenv").exists():
        identity["detected"] = "true"
        identity["runtime"] = "docker"

    cgroup = Path("/proc/self/cgroup")
    if cgroup.exists():
        try:
            text = cgroup.read_text()
        except OSError:  # pragma: no cover - defensive
            return identity
        match = _CONTAINER_ID.search(text)
        if match is not None:
            identity["detected"] = "true"
            identity["container_id"] = match.group(0)

    return identity


def tool_versions() -> dict[str, str]:
    """First line of ``--version`` for the external tools the run depends on."""
    versions: dict[str, str] = {}
    for tool, args in (
        ("git", ["--version"]),
        ("bwrap", ["--version"]),
        ("readelf", ["--version"]),
        ("cmake", ["--version"]),
    ):
        path = shutil.which(tool)
        if path is None:
            versions[tool] = "not found"
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                [path, *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
            versions[tool] = "unavailable"
            continue
        lines = completed.stdout.splitlines()
        versions[tool] = lines[0].strip() if lines else "unknown"
    return versions
