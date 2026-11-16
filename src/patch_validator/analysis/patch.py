"""Patch Analyzer — module 9 of the architecture.

Answers the central question of the project: *is this observed fault related
to what the patch changed?*

The specification is strict about what counts as an answer:

* Apparent adjacency between a fault and a diff is **not** proof of a
  relationship (SPEC 3.1).
* The crash site is **not** necessarily on a changed line; an indirect
  relationship through a caller, a callee or the execution path has to be
  considered.
* When the evidence is insufficient the relationship is ``UNKNOWN`` — not
  "probably related".

So correlation is graded rather than boolean, and the grade is derived from
what was actually observed:

    CONFIRMED  a stack frame lands on a line the patch changed
    LIKELY     a stack frame lands inside a function the patch changed
    WEAK       a stack frame only shares a file with the patch
    UNKNOWN    no usable frames, or no overlap at all

Only CONFIRMED and LIKELY promote a finding to "attributed to the patch".
WEAK and UNKNOWN keep the finding in the report with that exact label and
push the run towards an inconclusive verdict instead of a confident one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from ..config import Version
from ..vcs import GitRepo
from .cfunctions import FunctionRange, extract_functions, function_at
from .crash import CrashInfo
from .diffparse import FileDiff, Hunk, PatchDiff, parse_patch
from .frames import StackFrame

log = logging.getLogger(__name__)

CorrelationStatus = Literal["CONFIRMED", "LIKELY", "WEAK", "UNKNOWN"]
Confidence = Literal["high", "medium", "low", "none"]

#: Ordering used to pick the strongest evidence across frames.
_STATUS_RANK: dict[CorrelationStatus, int] = {
    "UNKNOWN": 0,
    "WEAK": 1,
    "LIKELY": 2,
    "CONFIRMED": 3,
}

_STATUS_CONFIDENCE: dict[CorrelationStatus, Confidence] = {
    "CONFIRMED": "high",
    "LIKELY": "medium",
    "WEAK": "low",
    "UNKNOWN": "none",
}


@dataclass(frozen=True)
class FrameMatch:
    """How one stack frame relates to the diff."""

    frame: StackFrame
    status: CorrelationStatus
    file: str = ""
    function: str = ""
    hunk: Hunk | None = None
    function_range: FunctionRange | None = None
    #: True when the file was matched on its basename rather than its path.
    matched_by_basename: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "frame": self.frame.to_dict(),
            "frame_description": self.frame.describe(),
            "status": self.status,
            "file": self.file,
            "function": self.function,
            "hunk": self.hunk.to_dict() if self.hunk else None,
            "function_range": (
                self.function_range.to_dict() if self.function_range else None
            ),
            "matched_by_basename": self.matched_by_basename,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class Correlation:
    """The Patch Correlation Report for one finding."""

    finding_id: str
    status: CorrelationStatus
    confidence: Confidence
    affected_file: str = ""
    affected_function: str = ""
    relevant_hunk: str = ""
    relevant_hunk_text: str = ""
    #: Index of the frame that produced the strongest match; > 0 means the
    #: relationship is indirect, through a caller of the faulting function.
    matched_frame_index: int | None = None
    indirect: bool = False
    stack_trace_evidence: tuple[str, ...] = ()
    correlation_evidence: tuple[str, ...] = ()
    frame_matches: tuple[FrameMatch, ...] = ()
    base_behavior: str = ""
    patched_behavior: str = ""
    notes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def attributed(self) -> bool:
        """Whether the evidence is strong enough to attribute to the patch."""
        return self.status in ("CONFIRMED", "LIKELY")

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "correlation_status": self.status,
            "confidence": self.confidence,
            "affected_file": self.affected_file,
            "affected_function": self.affected_function,
            "relevant_diff_hunk": self.relevant_hunk,
            "relevant_diff_hunk_text": self.relevant_hunk_text,
            "matched_frame_index": self.matched_frame_index,
            "indirect": self.indirect,
            "stack_trace_evidence": list(self.stack_trace_evidence),
            "correlation_evidence": list(self.correlation_evidence),
            "frame_matches": [match.to_dict() for match in self.frame_matches],
            "base_behavior": self.base_behavior,
            "patched_behavior": self.patched_behavior,
            "notes": list(self.notes),
            "evidence_refs": list(self.evidence_refs),
        }


class PatchAnalyzer:
    """Correlates observed faults with the lines the patch changed."""

    def __init__(
        self,
        repo: GitRepo,
        base_revision: str,
        patched_revision: str,
    ) -> None:
        self.repo = repo
        self.revisions: dict[Version, str] = {
            "base": base_revision,
            "patched": patched_revision,
        }
        self.diff: PatchDiff = parse_patch(
            repo.diff(base_revision, patched_revision)
        )
        self._functions: dict[tuple[str, str], tuple[FunctionRange, ...]] = {}
        log.info("patch touches %s", self.diff.summary())

    # -- public API --------------------------------------------------------

    def correlate(
        self,
        crash: CrashInfo,
        *,
        finding_id: str,
        base_behavior: str = "",
        patched_behavior: str = "",
    ) -> Correlation:
        """Relate one observed fault to the patch."""
        version: Version = crash.version  # type: ignore[assignment]
        side = "old" if version == "base" else "new"

        notes: list[str] = []
        if self.diff.is_empty:
            notes.append("the diff between the two revisions is empty")

        frames = crash.target_frames
        if not frames:
            return Correlation(
                finding_id=finding_id,
                status="UNKNOWN",
                confidence="none",
                base_behavior=base_behavior,
                patched_behavior=patched_behavior,
                notes=(
                    *notes,
                    "no symbolised stack frames were captured for this fault, "
                    "so no relationship to the diff can be established",
                    f"detected by {crash.detection_mechanism}, which reports "
                    "that a violation occurred but not where",
                ),
                evidence_refs=crash.evidence_refs,
            )

        matches = tuple(
            self._match_frame(frame, version=version, side=side) for frame in frames
        )
        best_index, best = _strongest(matches)

        indirect = best.status != "UNKNOWN" and best_index > 0
        evidence = _evidence_lines(matches, best_index, best, indirect)

        if best.status == "WEAK":
            notes.append(
                "only a shared file was found; adjacency between a fault and a "
                "diff is not sufficient evidence of a relationship"
            )
        if best.matched_by_basename:
            notes.append(
                "the file was matched on its name rather than its full path, "
                "because the build emitted no absolute source path"
            )
        if crash.signature_quality == "unsymbolized":
            notes.append(
                "frames carry no file or line information, so no better than "
                "module-level attribution is possible"
            )

        return Correlation(
            finding_id=finding_id,
            status=best.status,
            confidence=_STATUS_CONFIDENCE[best.status],
            affected_file=best.file,
            affected_function=best.function,
            relevant_hunk=best.hunk.header() if best.hunk else "",
            relevant_hunk_text="\n".join(best.hunk.lines) if best.hunk else "",
            matched_frame_index=best_index if best.status != "UNKNOWN" else None,
            indirect=indirect,
            stack_trace_evidence=tuple(frame.describe() for frame in frames),
            correlation_evidence=tuple(evidence),
            frame_matches=matches,
            base_behavior=base_behavior,
            patched_behavior=patched_behavior,
            notes=tuple(notes),
            evidence_refs=crash.evidence_refs,
        )

    def changed_functions(self) -> dict[str, set[str]]:
        """Map of changed file -> names of functions the patch touched."""
        result: dict[str, set[str]] = {}
        for file_diff in self.diff.files:
            if file_diff.status == "binary":
                continue
            names: set[str] = set()
            for version, side in (("base", "old"), ("patched", "new")):
                path = file_diff.old_path if side == "old" else file_diff.new_path
                if not path:
                    continue
                functions = self._functions_for(version, path)  # type: ignore[arg-type]
                changed = file_diff.changed_lines(side)  # type: ignore[arg-type]
                names.update(
                    function.name
                    for function in functions
                    if function.overlaps(changed)
                )
            result[file_diff.path] = names
        return result

    # -- internals ---------------------------------------------------------

    def _match_frame(
        self, frame: StackFrame, *, version: Version, side: str
    ) -> FrameMatch:
        if not frame.file:
            return FrameMatch(
                frame=frame,
                status="UNKNOWN",
                rationale="frame carries no source file",
            )

        file_diff = self.diff.file_for(frame.file)
        by_basename = False
        if file_diff is None:
            file_diff = self.diff.file_by_basename(frame.file.rsplit("/", 1)[-1])
            by_basename = file_diff is not None

        if file_diff is None:
            return FrameMatch(
                frame=frame,
                status="UNKNOWN",
                rationale=f"{frame.file} is not touched by the patch",
            )

        path = file_diff.old_path if side == "old" else file_diff.new_path
        function_range = self._function_for(version, path, frame.line)
        function_name = function_range.name if function_range else (frame.function or "")

        if frame.line is not None:
            for hunk in file_diff.hunks:
                if hunk.touches(frame.line, side=side):  # type: ignore[arg-type]
                    return FrameMatch(
                        frame=frame,
                        status="CONFIRMED",
                        file=file_diff.path,
                        function=function_name,
                        hunk=hunk,
                        function_range=function_range,
                        matched_by_basename=by_basename,
                        rationale=(
                            f"{frame.file}:{frame.line} is a line this patch "
                            f"changed ({hunk.header().strip()})"
                        ),
                    )

        changed = file_diff.changed_lines(side)  # type: ignore[arg-type]
        if function_range is not None and function_range.overlaps(changed):
            hunk = _hunk_for_function(file_diff, function_range, side)
            return FrameMatch(
                frame=frame,
                status="LIKELY",
                file=file_diff.path,
                function=function_name,
                hunk=hunk,
                function_range=function_range,
                matched_by_basename=by_basename,
                rationale=(
                    f"the fault is inside {function_name}() "
                    f"(lines {function_range.start_line}-{function_range.end_line}), "
                    "which the patch modified, but not on a changed line"
                ),
            )

        return FrameMatch(
            frame=frame,
            status="WEAK",
            file=file_diff.path,
            function=function_name,
            function_range=function_range,
            matched_by_basename=by_basename,
            rationale=(
                f"{file_diff.path} was modified by the patch, but the fault is "
                f"outside every changed function"
            ),
        )

    def _function_for(
        self, version: Version, path: str, line: int | None
    ) -> FunctionRange | None:
        if line is None or not path:
            return None
        return function_at(self._functions_for(version, path), line)

    def _functions_for(self, version: Version, path: str) -> tuple[FunctionRange, ...]:
        key = (version, path)
        if key in self._functions:
            return self._functions[key]
        source = self.repo.file_at(self.revisions[version], path)
        functions = extract_functions(source) if source else ()
        self._functions[key] = functions
        return functions


def _strongest(matches: tuple[FrameMatch, ...]) -> tuple[int, FrameMatch]:
    """Pick the best-evidenced frame, preferring the innermost on a tie."""
    best_index = 0
    best = matches[0]
    for index, match in enumerate(matches):
        if _STATUS_RANK[match.status] > _STATUS_RANK[best.status]:
            best_index, best = index, match
    return best_index, best


def _hunk_for_function(
    file_diff: FileDiff, function: FunctionRange, side: str
) -> Hunk | None:
    """The hunk that overlaps a function, for citing in the report."""
    for hunk in file_diff.hunks:
        if any(function.contains(line) for line in hunk.changed_lines(side)):
            return hunk
    return None


def _evidence_lines(
    matches: tuple[FrameMatch, ...],
    best_index: int,
    best: FrameMatch,
    indirect: bool,
) -> list[str]:
    evidence: list[str] = []
    if best.status == "UNKNOWN":
        evidence.append(
            "no stack frame falls in any file the patch changed"
        )
        return evidence

    evidence.append(f"frame #{best.frame.index}: {best.rationale}")
    if indirect:
        inner = matches[0].frame
        evidence.append(
            f"the relationship is indirect: the fault surfaced in "
            f"{inner.function or 'an unnamed frame'} at {inner.location()}, "
            f"which is reached from the changed code"
        )
    for index, match in enumerate(matches):
        if index == best_index or match.status == "UNKNOWN":
            continue
        evidence.append(f"frame #{match.frame.index}: {match.rationale}")
    return evidence
