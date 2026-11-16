"""Artifact store for one validation run.

Every claim the tool makes has to point at something on disk.  All of it lands
under a single run directory, and findings reference artifacts by a path
relative to that directory, so the whole run can be archived or uploaded as a
CI artifact and still make sense (R-CICD-05).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def new_run_id(now: datetime | None = None) -> str:
    """A sortable, filesystem-safe identifier for one run."""
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y%m%dT%H%M%SZ")


class ArtifactStore:
    """Writes run artifacts and hands back references to them."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative: str) -> Path:
        """Absolute path for ``relative``, with parent directories created."""
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def ref(self, path: Path) -> str:
        """The reference form of ``path``: relative to the run root."""
        try:
            return str(path.resolve().relative_to(self.root))
        except ValueError:
            # Outside the store (for example a path inside the target repo).
            return str(path)

    def write_bytes(self, relative: str, data: bytes) -> str:
        target = self.path(relative)
        target.write_bytes(data)
        return self.ref(target)

    def write_text(self, relative: str, text: str) -> str:
        target = self.path(relative)
        target.write_text(text, encoding="utf-8")
        return self.ref(target)

    def write_json(self, relative: str, payload: Any) -> str:
        target = self.path(relative)
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return self.ref(target)

    def subdir(self, relative: str) -> Path:
        target = self.root / relative
        target.mkdir(parents=True, exist_ok=True)
        return target
