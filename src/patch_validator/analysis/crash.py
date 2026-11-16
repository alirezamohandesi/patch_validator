"""Crash Analyzer — module 6 of the architecture.

Turns one raw execution result into a classified observation.

Three boundaries are deliberate and load-bearing:

* **Classification is not root cause analysis.**  The analyzer names what was
  observed and the mechanism that observed it.  It never claims why the defect
  exists (R-DYN-13).
* **A crash is not a vulnerability.**  Nothing here decides exploitability; a
  non-zero exit code on its own is not even a crash (R-DYN-14).
* **Resource exhaustion is not a security finding.**  Timeouts and limit hits
  get their own outcome so they can be reported without being counted as
  memory errors (R-DYN-07).
"""

from __future__ import annotations

import dataclasses
import logging
import re
import signal as signal_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..execution import ExecutionResult
from ..util.hashing import sha256_bytes
from .frames import StackFrame, normalize_path, parse_frames, target_frames

log = logging.getLogger(__name__)

Outcome = Literal[
    "clean",
    "security_event",
    "crash_unclassified",
    "timeout",
    "resource_limit",
    "launch_failure",
]

Confidence = Literal["high", "medium", "low"]

DetectionMechanism = Literal[
    "address_sanitizer",
    "undefined_behavior_sanitizer",
    "leak_sanitizer",
    "stack_protector",
    "fortify_source",
    "glibc_malloc_check",
    "os_signal",
    "runtime_diagnostic",
    "resource_limit",
    "none",
]

#: Number of leading target frames folded into a signature.
SIGNATURE_FRAMES = 3

_ASAN_ERROR = re.compile(
    r"ERROR:\s+AddressSanitizer:\s+(?P<kind>[a-zA-Z0-9_-]+)"
    r"(?P<detail>[^\n]*)"
)
_LSAN_ERROR = re.compile(r"ERROR:\s+LeakSanitizer:\s+(?P<kind>[^\n]+)")
_UBSAN_ERROR = re.compile(
    r"(?P<file>[^\s:]+):(?P<line>\d+):(?P<column>\d+):\s+runtime error:\s+(?P<message>[^\n]+)"
)
_ASAN_SUMMARY = re.compile(r"SUMMARY:\s+\w+Sanitizer:\s+(?P<kind>\S+)\s*(?P<where>[^\n]*)")
_ASAN_ADDRESS = re.compile(r"on (?:unknown )?address 0x(?P<address>[0-9a-f]+)")

#: ASan error kind -> the error type reported.
_ASAN_TYPES: dict[str, str] = {
    "stack-buffer-overflow": "STACK_BUFFER_OVERFLOW",
    "dynamic-stack-buffer-overflow": "STACK_BUFFER_OVERFLOW",
    "stack-buffer-underflow": "STACK_BUFFER_UNDERFLOW",
    "heap-buffer-overflow": "HEAP_BUFFER_OVERFLOW",
    "global-buffer-overflow": "GLOBAL_BUFFER_OVERFLOW",
    "heap-use-after-free": "USE_AFTER_FREE",
    "stack-use-after-return": "USE_AFTER_RETURN",
    "stack-use-after-scope": "USE_AFTER_SCOPE",
    "double-free": "DOUBLE_FREE",
    "attempting-double-free": "DOUBLE_FREE",
    "bad-free": "INVALID_FREE",
    "alloc-dealloc-mismatch": "ALLOC_DEALLOC_MISMATCH",
    "stack-overflow": "STACK_EXHAUSTION",
    "SEGV": "SEGMENTATION_FAULT",
    "BUS": "BUS_ERROR",
    "FPE": "ARITHMETIC_FAULT",
    "ILL": "ILLEGAL_INSTRUCTION",
    "allocation-size-too-big": "ALLOCATION_SIZE_TOO_BIG",
    "requested-allocation-size-exceeds-maximum-supported-size": "ALLOCATION_SIZE_TOO_BIG",
}

#: Substring of a UBSan runtime-error message -> error type.
_UBSAN_TYPES: tuple[tuple[str, str], ...] = (
    ("signed integer overflow", "INTEGER_OVERFLOW"),
    ("unsigned integer overflow", "INTEGER_OVERFLOW"),
    ("integer overflow", "INTEGER_OVERFLOW"),
    ("division by zero", "DIVISION_BY_ZERO"),
    ("divide by zero", "DIVISION_BY_ZERO"),
    ("out of bounds", "ARRAY_OUT_OF_BOUNDS"),
    ("null pointer", "NULL_POINTER_DEREFERENCE"),
    ("misaligned address", "MISALIGNED_ACCESS"),
    ("shift exponent", "INVALID_SHIFT"),
    ("not a valid value", "INVALID_ENUM_VALUE"),
)

#: glibc runtime diagnostics printed just before abort().
_GLIBC_DIAGNOSTICS: tuple[tuple[str, str, DetectionMechanism], ...] = (
    ("stack smashing detected", "STACK_BUFFER_OVERFLOW", "stack_protector"),
    ("buffer overflow detected", "BUFFER_OVERFLOW", "fortify_source"),
    ("double free or corruption", "DOUBLE_FREE", "glibc_malloc_check"),
    ("free(): invalid pointer", "INVALID_FREE", "glibc_malloc_check"),
    ("free(): double free", "DOUBLE_FREE", "glibc_malloc_check"),
    ("munmap_chunk(): invalid pointer", "INVALID_FREE", "glibc_malloc_check"),
    ("malloc(): corrupted top size", "HEAP_CORRUPTION", "glibc_malloc_check"),
    ("malloc(): invalid size", "HEAP_CORRUPTION", "glibc_malloc_check"),
    ("corrupted size vs. prev_size", "HEAP_CORRUPTION", "glibc_malloc_check"),
    ("corrupted double-linked list", "HEAP_CORRUPTION", "glibc_malloc_check"),
)

#: Signal -> (error type, whether it indicates a memory-safety class fault).
_SIGNAL_TYPES: dict[int, tuple[str, bool]] = {
    signal_module.SIGSEGV: ("SEGMENTATION_FAULT", True),
    signal_module.SIGBUS: ("BUS_ERROR", True),
    signal_module.SIGILL: ("ILLEGAL_INSTRUCTION", True),
    signal_module.SIGFPE: ("ARITHMETIC_FAULT", True),
    signal_module.SIGABRT: ("ABORT", True),
    signal_module.SIGSYS: ("BAD_SYSCALL", True),
    signal_module.SIGTRAP: ("TRAP", True),
}

#: Signals that mean a limit was reached, not that the program is unsafe.
_RESOURCE_SIGNALS = {
    signal_module.SIGXCPU: "cpu_time",
    signal_module.SIGXFSZ: "file_size",
}


@dataclass(frozen=True)
class CrashInfo:
    """Classified observation of one execution."""

    test_id: str
    version: str
    build_mode: str
    outcome: Outcome
    error_type: str
    detection_mechanism: DetectionMechanism
    confidence: Confidence

    #: Termination facts, repeated here so a finding is self-contained.
    exit_code: int | None = None
    signal: int | None = None
    signal_name: str | None = None
    signal_inferred: bool = False
    timed_out: bool = False

    message: str = ""
    fault_address: str = ""
    frames: tuple[StackFrame, ...] = ()
    target_frames: tuple[StackFrame, ...] = ()
    #: Precise identity of this fault: type, mechanism and top frames with
    #: line numbers.  Used to decide whether a minimised input still triggers
    #: the same bug in the same binary.
    signature: str = ""
    #: Line-insensitive identity: same, minus line numbers.  Used to compare a
    #: fault across base and patched, where a patch shifts line numbers.
    location_signature: str = ""
    signature_quality: Literal["symbolized", "unsymbolized", "none"] = "none"
    notes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_security_event(self) -> bool:
        """Whether this observation belongs on the security axis at all."""
        return self.outcome == "security_event"

    @property
    def location(self) -> str:
        for frame in self.target_frames:
            if frame.has_source:
                return frame.location()
        return self.target_frames[0].location() if self.target_frames else ""

    def summary(self) -> str:
        where = f" at {self.location}" if self.location else ""
        return f"{self.error_type} via {self.detection_mechanism}{where}"

    def to_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "version": self.version,
            "build_mode": self.build_mode,
            "outcome": self.outcome,
            "error_type": self.error_type,
            "detection_mechanism": self.detection_mechanism,
            "confidence": self.confidence,
            "termination": {
                "exit_code": self.exit_code,
                "signal": self.signal,
                "signal_name": self.signal_name,
                "signal_inferred": self.signal_inferred,
                "timed_out": self.timed_out,
            },
            "message": self.message,
            "fault_address": self.fault_address,
            "location": self.location,
            "frames": [frame.to_dict() for frame in self.frames],
            "target_frames": [frame.to_dict() for frame in self.target_frames],
            "crash_signature": self.signature,
            "location_signature": self.location_signature,
            "signature_quality": self.signature_quality,
            "notes": list(self.notes),
            "evidence_refs": list(self.evidence_refs),
            "extra": dict(self.extra),
        }


class CrashAnalyzer:
    """Classifies execution results into crash observations."""

    def __init__(self, source_roots: tuple[Path, ...] = ()) -> None:
        #: Worktree roots of the versions under test, used to normalise paths
        #: and to tell target frames from toolchain frames.
        self.source_roots = source_roots

    def analyze(self, result: ExecutionResult) -> CrashInfo:
        stderr = result.stderr_text()
        stdout = result.stdout_text()
        notes: list[str] = []

        if result.launch_error:
            return self._build(
                result,
                outcome="launch_failure",
                error_type="LAUNCH_FAILURE",
                mechanism="none",
                confidence="high",
                message=result.launch_error,
                notes=("the target could not be started; this is not a finding",),
            )

        # Resource exhaustion is checked first: a timeout that also produced a
        # partial sanitizer report must not be read as a memory error.
        if result.timed_out:
            return self._build(
                result,
                outcome="timeout",
                error_type="TIMEOUT",
                mechanism="resource_limit",
                confidence="high",
                message=f"no exit within {result.timeout_s}s",
                notes=(
                    "a timeout is reported but never classified as a "
                    "vulnerability on its own",
                ),
            )

        if result.signal in _RESOURCE_SIGNALS:
            kind = _RESOURCE_SIGNALS[result.signal]
            return self._build(
                result,
                outcome="resource_limit",
                error_type=f"RESOURCE_LIMIT_{kind.upper()}",
                mechanism="resource_limit",
                confidence="high",
                message=f"terminated by {result.signal_name} ({kind} limit)",
                notes=(
                    "a resource limit is reported but never classified as a "
                    "vulnerability on its own",
                ),
            )

        combined = f"{stderr}\n{stdout}"
        frames = parse_frames(stderr) or parse_frames(stdout)

        for detector in (
            self._detect_address_sanitizer,
            self._detect_leak_sanitizer,
            self._detect_undefined_behavior,
            self._detect_glibc_diagnostic,
        ):
            detected = detector(result, combined, frames, notes)
            if detected is not None:
                return detected

        if result.signal is not None:
            return self._detect_signal(result, frames, notes)

        if result.stdout_truncated or result.stderr_truncated:
            notes.append("output was truncated at the configured cap")

        return self._build(
            result,
            outcome="clean",
            error_type="NONE",
            mechanism="none",
            confidence="high",
            message="",
            frames=frames,
            notes=tuple(notes),
        )

    # -- detectors ---------------------------------------------------------

    def _detect_address_sanitizer(
        self,
        result: ExecutionResult,
        text: str,
        frames: list[StackFrame],
        notes: list[str],
    ) -> CrashInfo | None:
        match = _ASAN_ERROR.search(text)
        if match is None:
            return None

        kind = match.group("kind")
        error_type = _ASAN_TYPES.get(kind, "")
        local_notes = list(notes)
        if not error_type:
            summary = _ASAN_SUMMARY.search(text)
            if summary is not None:
                error_type = _ASAN_TYPES.get(summary.group("kind"), "")
        if not error_type:
            error_type = f"ASAN_{kind.upper().replace('-', '_')}"
            local_notes.append(
                f"unmapped AddressSanitizer category '{kind}'; reported verbatim"
            )

        address = ""
        address_match = _ASAN_ADDRESS.search(text)
        if address_match is not None:
            address = f"0x{address_match.group('address')}"
            if error_type == "SEGMENTATION_FAULT" and _is_null_page(address):
                error_type = "NULL_POINTER_DEREFERENCE"

        return self._build(
            result,
            outcome="security_event",
            error_type=error_type,
            mechanism="address_sanitizer",
            confidence="high",
            message=f"AddressSanitizer: {kind}{match.group('detail').strip()}",
            fault_address=address,
            frames=frames,
            notes=tuple(local_notes),
        )

    def _detect_leak_sanitizer(
        self,
        result: ExecutionResult,
        text: str,
        frames: list[StackFrame],
        notes: list[str],
    ) -> CrashInfo | None:
        match = _LSAN_ERROR.search(text)
        if match is None:
            return None
        return self._build(
            result,
            outcome="security_event",
            error_type="MEMORY_LEAK",
            mechanism="leak_sanitizer",
            confidence="high",
            message=f"LeakSanitizer: {match.group('kind').strip()}",
            frames=frames,
            notes=(*notes, "a leak is a resource defect, not a memory-safety violation"),
        )

    def _detect_undefined_behavior(
        self,
        result: ExecutionResult,
        text: str,
        frames: list[StackFrame],
        notes: list[str],
    ) -> CrashInfo | None:
        match = _UBSAN_ERROR.search(text)
        if match is None:
            return None

        message = match.group("message").strip()
        error_type = "UNDEFINED_BEHAVIOR"
        lowered = message.lower()
        for needle, mapped in _UBSAN_TYPES:
            if needle in lowered:
                error_type = mapped
                break

        # UBSan reports its own location even without a back-trace, so
        # synthesise a frame when none was printed.
        if not frames:
            frames = [
                StackFrame(
                    index=0,
                    function="",
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("column")),
                    raw=match.group(0),
                )
            ]

        return self._build(
            result,
            outcome="security_event",
            error_type=error_type,
            mechanism="undefined_behavior_sanitizer",
            confidence="high",
            message=f"runtime error: {message}",
            frames=frames,
            notes=tuple(notes),
        )

    def _detect_glibc_diagnostic(
        self,
        result: ExecutionResult,
        text: str,
        frames: list[StackFrame],
        notes: list[str],
    ) -> CrashInfo | None:
        for needle, error_type, mechanism in _GLIBC_DIAGNOSTICS:
            if needle not in text:
                continue
            local_notes = [
                *notes,
                "detected by a runtime check in the C library, which reports "
                "that a bound was violated but not where the write began",
            ]
            if result.signal is None:
                local_notes.append(
                    "the diagnostic was printed but the process did not abort"
                )
            return self._build(
                result,
                outcome="security_event",
                error_type=error_type,
                mechanism=mechanism,
                # The mechanism proves a violation occurred; it does not
                # localise it, so a symbolised frame is not available.
                confidence="high" if result.signal is not None else "medium",
                message=needle,
                frames=frames,
                notes=tuple(local_notes),
            )
        return None

    def _detect_signal(
        self,
        result: ExecutionResult,
        frames: list[StackFrame],
        notes: list[str],
    ) -> CrashInfo:
        assert result.signal is not None
        error_type, is_fault = _SIGNAL_TYPES.get(result.signal, ("SIGNAL", False))
        local_notes = list(notes)

        if result.signal_inferred:
            local_notes.append(
                "the signal was derived from a 128+N exit code reported by the "
                "sandbox helper and is corroborated only by the captured output"
            )

        if result.signal == signal_module.SIGKILL:
            return self._build(
                result,
                outcome="resource_limit",
                error_type="KILLED",
                mechanism="resource_limit",
                confidence="medium",
                message="terminated by SIGKILL, most likely a resource ceiling",
                frames=frames,
                notes=(
                    *local_notes,
                    "SIGKILL leaves no diagnostic; the cause is not established",
                ),
            )

        confidence: Confidence = "medium" if result.signal_inferred else "high"
        return self._build(
            result,
            outcome="security_event" if is_fault else "crash_unclassified",
            error_type=error_type,
            mechanism="os_signal",
            confidence=confidence,
            message=f"terminated by {result.signal_name}",
            frames=frames,
            notes=(
                *local_notes,
                "the operating system reported a fault; the specific memory "
                "error class is not determined without a sanitizer",
            ),
        )

    # -- construction ------------------------------------------------------

    def _build(
        self,
        result: ExecutionResult,
        *,
        outcome: Outcome,
        error_type: str,
        mechanism: DetectionMechanism,
        confidence: Confidence,
        message: str,
        fault_address: str = "",
        frames: list[StackFrame] | None = None,
        notes: tuple[str, ...] = (),
    ) -> CrashInfo:
        all_frames = tuple(frames or ())
        # Target frames carry repository-relative paths: that is the form the
        # diff speaks, and it is identical for the base worktree and the
        # patched worktree, which is what lets the two be compared at all.
        relevant = tuple(
            dataclasses.replace(
                frame, file=normalize_path(frame.file, self.source_roots)
            )
            for frame in target_frames(list(all_frames), self.source_roots)
        )

        signature = ""
        location_signature = ""
        quality: Literal["symbolized", "unsymbolized", "none"] = "none"
        if outcome in ("security_event", "crash_unclassified"):
            signature, location_signature, quality = self._signatures(
                error_type, mechanism, relevant
            )

        evidence = tuple(ref for ref in (result.stderr_ref, result.stdout_ref) if ref)

        return CrashInfo(
            test_id=result.test_id,
            version=result.version,
            build_mode=result.build_mode,
            outcome=outcome,
            error_type=error_type,
            detection_mechanism=mechanism,
            confidence=confidence,
            exit_code=result.exit_code,
            signal=result.signal,
            signal_name=result.signal_name,
            signal_inferred=result.signal_inferred,
            timed_out=result.timed_out,
            message=message,
            fault_address=fault_address,
            frames=all_frames,
            target_frames=relevant,
            signature=signature,
            location_signature=location_signature,
            signature_quality=quality,
            notes=notes,
            evidence_refs=evidence,
        )

    def _signatures(
        self,
        error_type: str,
        mechanism: str,
        frames: tuple[StackFrame, ...],
    ) -> tuple[str, str, Literal["symbolized", "unsymbolized", "none"]]:
        """Build the precise and the line-insensitive fault identities."""
        head = frames[:SIGNATURE_FRAMES]
        if not head:
            # No frames at all: the type and mechanism are all we can bind to.
            # Still stable, just coarse.
            seed = f"{error_type}|{mechanism}"
            digest = sha256_bytes(seed.encode())
            return digest, digest, "none"

        symbolized = any(frame.has_source for frame in head)
        precise: list[str] = []
        coarse: list[str] = []
        for frame in head:
            file = frame.file
            function = frame.function or "??"
            if frame.has_source:
                precise.append(f"{function}@{file}:{frame.line}")
                coarse.append(f"{function}@{file}")
            else:
                module = Path(frame.module).name if frame.module else ""
                precise.append(f"{function}@{module}+0x{frame.offset}")
                coarse.append(f"{function}@{module}")

        prefix = f"{error_type}|{mechanism}"
        return (
            sha256_bytes("|".join([prefix, *precise]).encode()),
            sha256_bytes("|".join([prefix, *coarse]).encode()),
            "symbolized" if symbolized else "unsymbolized",
        )


def _is_null_page(address: str) -> bool:
    """Whether a fault address lies in the first page, i.e. a null deref."""
    try:
        return int(address, 16) < 0x1000
    except ValueError:  # pragma: no cover - defensive
        return False
