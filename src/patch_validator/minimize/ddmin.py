"""Testcase Minimizer — module 10 of the architecture.

Shrinks a fault-triggering input while keeping the fault *the same fault*.

The predicate is what makes this honest.  "Still exits non-zero" is explicitly
not an acceptable criterion (SPEC 3.3): a smaller input that crashes somewhere
else is a different bug, and a regression test built from it would test the
wrong thing.  The predicate here compares the full crash signature — error
type, detection mechanism and the top target frames with their line numbers —
so a reduction is only accepted when the same error still happens in the same
place.

The algorithm is ddmin on the byte sequence: delete increasingly fine-grained
chunks, keep whatever still satisfies the predicate, and give up when no
single chunk at the finest granularity can be removed.  It is format agnostic
by construction, which is the point — nothing here knows what the target
parses.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import MinimizationSpec
from ..util.hashing import sha256_bytes

log = logging.getLogger(__name__)

#: Returns True when the candidate still triggers the original fault.
Predicate = Callable[[bytes], bool]


@dataclass(frozen=True)
class Attempt:
    """One candidate the minimizer tried."""

    iteration: int
    size: int
    granularity: int
    accepted: bool
    cached: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "size": self.size,
            "granularity": self.granularity,
            "accepted": self.accepted,
            "cached": self.cached,
        }


@dataclass(frozen=True)
class MinimizationResult:
    finding_id: str
    original: bytes
    minimized: bytes
    iterations: int
    duration_s: float
    stop_reason: str
    predicate_description: str
    attempts: tuple[Attempt, ...] = ()
    original_ref: str = ""
    minimized_ref: str = ""
    trace_ref: str = ""
    verified: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def original_size(self) -> int:
        return len(self.original)

    @property
    def minimized_size(self) -> int:
        return len(self.minimized)

    @property
    def reduction_percent(self) -> float:
        if not self.original:
            return 0.0
        removed = self.original_size - self.minimized_size
        return round(100.0 * removed / self.original_size, 2)

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "original_size": self.original_size,
            "minimized_size": self.minimized_size,
            "reduction_percent": self.reduction_percent,
            "original_sha256": sha256_bytes(self.original),
            "minimized_sha256": sha256_bytes(self.minimized),
            "iterations": self.iterations,
            "duration_s": round(self.duration_s, 3),
            "stop_reason": self.stop_reason,
            "predicate": self.predicate_description,
            "verified": self.verified,
            "original_ref": self.original_ref,
            "minimized_ref": self.minimized_ref,
            "trace_ref": self.trace_ref,
            "notes": list(self.notes),
        }


class Minimizer:
    """ddmin over the bytes of an input."""

    def __init__(self, spec: MinimizationSpec) -> None:
        self.spec = spec

    def minimize(
        self,
        data: bytes,
        predicate: Predicate,
        *,
        finding_id: str,
        predicate_description: str,
    ) -> MinimizationResult:
        started = time.monotonic()
        attempts: list[Attempt] = []
        # Candidates are cached by content hash: ddmin revisits the same
        # byte sequence often, and every miss costs a full sandboxed run.
        seen: dict[str, bool] = {}
        iterations = 0
        stop_reason = "no further reduction possible"

        current = data
        granularity = 2

        def holds(candidate: bytes) -> bool:
            nonlocal iterations
            digest = sha256_bytes(candidate)
            if digest in seen:
                attempts.append(
                    Attempt(iterations, len(candidate), granularity, seen[digest], True)
                )
                return seen[digest]
            iterations += 1
            outcome = predicate(candidate)
            seen[digest] = outcome
            attempts.append(
                Attempt(iterations, len(candidate), granularity, outcome, False)
            )
            return outcome

        while len(current) >= 2:
            if iterations >= self.spec.max_iterations:
                stop_reason = f"iteration budget exhausted ({self.spec.max_iterations})"
                break
            if time.monotonic() - started >= self.spec.budget_seconds:
                stop_reason = f"time budget exhausted ({self.spec.budget_seconds}s)"
                break

            chunks = _split(current, granularity)
            reduced = False

            for index in range(len(chunks)):
                candidate = b"".join(chunks[:index] + chunks[index + 1 :])
                if not candidate:
                    continue
                if holds(candidate):
                    current = candidate
                    # Removing one of n chunks leaves n-1; continuing at that
                    # granularity is what keeps ddmin from immediately
                    # re-splitting into pieces that are too small.
                    granularity = max(granularity - 1, 2)
                    reduced = True
                    break

            if reduced:
                continue
            if granularity >= len(current):
                break
            granularity = min(granularity * 2, len(current))

        duration = time.monotonic() - started
        notes: list[str] = []
        if len(current) == len(data):
            notes.append(
                "no byte could be removed without changing the fault; the "
                "input is already minimal with respect to this predicate"
            )
        if "budget" in stop_reason:
            notes.append(
                "the result is the smallest input found within the budget, "
                "not a proven minimum"
            )

        result = MinimizationResult(
            finding_id=finding_id,
            original=data,
            minimized=current,
            iterations=iterations,
            duration_s=duration,
            stop_reason=stop_reason,
            predicate_description=predicate_description,
            attempts=tuple(attempts),
            notes=tuple(notes),
        )
        log.info(
            "minimized %s: %d -> %d bytes (%.1f%%) in %d executions, %s",
            finding_id,
            result.original_size,
            result.minimized_size,
            result.reduction_percent,
            iterations,
            stop_reason,
        )
        return result


def _split(data: bytes, parts: int) -> list[bytes]:
    """Split into ``parts`` near-equal chunks, dropping empty ones."""
    parts = max(2, min(parts, len(data)))
    size, remainder = divmod(len(data), parts)
    chunks: list[bytes] = []
    offset = 0
    for index in range(parts):
        length = size + (1 if index < remainder else 0)
        if length == 0:
            continue
        chunks.append(data[offset : offset + length])
        offset += length
    return chunks
