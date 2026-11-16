"""Content hashing.

Hashes appear throughout the report: every binary, every input and every
crash signature is identified by one, which is what makes a finding
referenceable and a reproduction checkable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def short(digest: str, length: int = 12) -> str:
    """Shorten a hex digest for use in identifiers and log lines."""
    return digest[:length]
