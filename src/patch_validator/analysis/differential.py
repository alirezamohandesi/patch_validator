"""Differential Tester — module 8 of the architecture.

Compares the behaviour of the base and the patched build on the same input,
under the same settings, in the same build mode, and turns the comparison
into findings.

Two rules from the specification are enforced here rather than left to
convention:

* A comparison is only ever made between **corresponding** builds.  Release
  results and sanitized results are never mixed, because instrumentation
  changes what is observable (SPEC 3.2).
* A functional regression requires proof on *both* sides: the base matched
  the independent oracle and the patched build broke it.  If the base already
  violated the oracle, a difference between the two versions is reported as
  inconclusive, never as a regression (SPEC 3.1, R-CORE-12/13).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import BuildMode, TestCase
from ..execution import ExecutionResult
from .crash import CrashInfo
from .findings import Confidence, Finding
from .oracle import OracleVerdict

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CasePair:
    """Everything observed for one test case in one build mode."""

    case: TestCase
    build_mode: BuildMode
    base_result: ExecutionResult
    patched_result: ExecutionResult
    base_crash: CrashInfo
    patched_crash: CrashInfo
    base_oracle: OracleVerdict
    patched_oracle: OracleVerdict

    def __post_init__(self) -> None:
        # Guard rather than document: mixing build modes would silently
        # invalidate every conclusion drawn from this pair.
        if self.base_result.build_mode != self.patched_result.build_mode:
            raise ValueError(
                "refusing to compare different build modes: "
                f"{self.base_result.build_mode} vs {self.patched_result.build_mode}"
            )
        if self.base_result.version != "base" or self.patched_result.version != "patched":
            raise ValueError("CasePair expects one base and one patched result")


class DifferentialTester:
    """Derives findings from paired base/patched observations."""

    #: Build mode whose functional verdict decides the run.
    authoritative_mode: BuildMode = "release"

    def compare(self, pair: CasePair) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._security_axis(pair))
        findings.extend(self._functional_axis(pair))
        findings.extend(self._completeness_axis(pair))
        return findings

    # -- security ----------------------------------------------------------

    def _security_axis(self, pair: CasePair) -> list[Finding]:
        base, patched = pair.base_crash, pair.patched_crash
        base_fault = _is_fault(base)
        patched_fault = _is_fault(patched)

        if not base_fault and not patched_fault:
            return []

        identifier = f"sec/{pair.case.id}/{pair.build_mode}"
        evidence = (*base.evidence_refs, *patched.evidence_refs)
        base_behavior = _describe(base)
        patched_behavior = _describe(patched)

        if base_fault and not patched_fault:
            return [
                Finding(
                    id=identifier,
                    axis="security",
                    kind="FIXED",
                    test_id=pair.case.id,
                    build_mode=pair.build_mode,
                    summary=(
                        f"{base.error_type} observed on base is no longer "
                        f"observed on the patched build"
                    ),
                    confidence=_weakest(base.confidence, "high"),
                    base_behavior=base_behavior,
                    patched_behavior=patched_behavior,
                    base_crash=base,
                    patched_crash=patched,
                    notes=(
                        "absence of the fault for this input does not prove the "
                        "defect class was eliminated everywhere",
                    ),
                    evidence_refs=evidence,
                )
            ]

        if base_fault and patched_fault:
            same_place = base.location_signature == patched.location_signature
            notes = [
                "the input that triggered the original fault still triggers a "
                "fault after the patch",
            ]
            if not same_place:
                notes.append(
                    "the fault moved: "
                    f"base at {base.location or 'an unknown location'} "
                    f"({base.error_type}), patched at "
                    f"{patched.location or 'an unknown location'} "
                    f"({patched.error_type})"
                )
            return [
                Finding(
                    id=identifier,
                    axis="security",
                    kind="INCOMPLETE_FIX",
                    test_id=pair.case.id,
                    build_mode=pair.build_mode,
                    summary=(
                        f"{patched.error_type} still reproduces on the patched "
                        f"build for this input"
                    ),
                    confidence="high" if same_place else "medium",
                    base_behavior=base_behavior,
                    patched_behavior=patched_behavior,
                    base_crash=base,
                    patched_crash=patched,
                    signature_changed=not same_place,
                    notes=tuple(notes),
                    evidence_refs=evidence,
                )
            ]

        # Fault only on the patched build.
        return [
            Finding(
                id=identifier,
                axis="security",
                kind="NEW_ISSUE",
                test_id=pair.case.id,
                build_mode=pair.build_mode,
                summary=(
                    f"{patched.error_type} is observed on the patched build but "
                    f"not on the base build"
                ),
                confidence=_weakest(patched.confidence, "medium"),
                base_behavior=base_behavior,
                patched_behavior=patched_behavior,
                base_crash=base,
                patched_crash=patched,
                notes=(
                    "observing a fault for the first time does not by itself "
                    "establish that the patch caused it; see the correlation",
                ),
                evidence_refs=evidence,
            )
        ]

    # -- functional --------------------------------------------------------

    def _functional_axis(self, pair: CasePair) -> list[Finding]:
        base, patched = pair.base_oracle, pair.patched_oracle
        if not base.applicable or not patched.applicable:
            return []

        identifier = f"func/{pair.case.id}/{pair.build_mode}"
        authoritative = pair.build_mode == self.authoritative_mode
        evidence = (
            pair.base_result.stdout_ref,
            pair.base_result.stderr_ref,
            pair.patched_result.stdout_ref,
            pair.patched_result.stderr_ref,
        )
        evidence = tuple(ref for ref in evidence if ref)
        base_behavior = _describe_behavior(pair.base_result)
        patched_behavior = _describe_behavior(pair.patched_result)

        common = {
            "test_id": pair.case.id,
            "build_mode": pair.build_mode,
            "base_behavior": base_behavior,
            "patched_behavior": patched_behavior,
            "base_oracle": base,
            "patched_oracle": patched,
            "authoritative": authoritative,
            "evidence_refs": evidence,
        }

        if base.matched and patched.matched:
            return []

        if base.matched and not patched.matched:
            return [
                Finding(
                    id=identifier,
                    axis="functional",
                    kind="FUNCTIONAL_REGRESSION",
                    summary=(
                        f"behaviour required by the specification was correct on "
                        f"base and is violated on the patched build: "
                        f"{patched.describe()}"
                    ),
                    confidence="high",
                    notes=(
                        "the base build satisfied the independent oracle for this "
                        "input, so the difference is attributable to the patch",
                        f"oracle source: {patched.oracle_source}",
                    ),
                    **common,  # type: ignore[arg-type]
                )
            ]

        if not base.matched and patched.matched:
            return [
                Finding(
                    id=identifier,
                    axis="functional",
                    kind="FUNCTIONAL_FIX",
                    summary=(
                        "the patched build now satisfies a specification "
                        "requirement that the base build violated"
                    ),
                    confidence="high",
                    notes=("informational; this is an improvement, not a defect",),
                    **common,  # type: ignore[arg-type]
                )
            ]

        # Neither side matches the oracle.
        if _same_observable_behavior(pair.base_result, pair.patched_result):
            return [
                Finding(
                    id=identifier,
                    axis="functional",
                    kind="PRE_EXISTING_DEFECT",
                    summary=(
                        "both builds violate the specification for this input, "
                        "identically"
                    ),
                    confidence="high",
                    notes=(
                        "pre-existing deviation; the patch neither caused nor "
                        "fixed it",
                    ),
                    **common,  # type: ignore[arg-type]
                )
            ]

        return [
            Finding(
                id=identifier,
                axis="functional",
                kind="INCONCLUSIVE",
                summary=(
                    "both builds violate the specification for this input, in "
                    "different ways"
                ),
                confidence="low",
                notes=(
                    "the base build did not satisfy the oracle, so a difference "
                    "between the two versions cannot be called a functional "
                    "regression",
                    f"base: {base.describe()}",
                    f"patched: {patched.describe()}",
                ),
                **common,  # type: ignore[arg-type]
            )
        ]

    # -- completeness ------------------------------------------------------

    def _completeness_axis(self, pair: CasePair) -> list[Finding]:
        findings: list[Finding] = []
        identifier = f"gap/{pair.case.id}/{pair.build_mode}"

        if not pair.base_oracle.applicable or not pair.patched_oracle.applicable:
            findings.append(
                Finding(
                    id=f"{identifier}/oracle",
                    axis="completeness",
                    kind="MISSING_ORACLE",
                    test_id=pair.case.id,
                    build_mode=pair.build_mode,
                    summary=(
                        f"test '{pair.case.id}' has no oracle, so it contributes "
                        f"nothing to the functional verdict"
                    ),
                    confidence="high",
                    notes=(
                        "the input was still executed and still contributes to "
                        "the security axis",
                    ),
                )
            )

        for crash in (pair.base_crash, pair.patched_crash):
            if crash.outcome in ("timeout", "resource_limit"):
                findings.append(
                    Finding(
                        id=f"{identifier}/{crash.version}/limit",
                        axis="completeness",
                        kind="RESOURCE_LIMIT",
                        test_id=pair.case.id,
                        build_mode=pair.build_mode,
                        summary=(
                            f"the {crash.version} build hit a limit for this "
                            f"input: {crash.message}"
                        ),
                        confidence=crash.confidence,
                        notes=(
                            "the comparison for this input is incomplete; a "
                            "limit is never classified as a vulnerability",
                            *crash.notes,
                        ),
                        evidence_refs=crash.evidence_refs,
                    )
                )
            elif crash.outcome == "launch_failure":
                findings.append(
                    Finding(
                        id=f"{identifier}/{crash.version}/launch",
                        axis="completeness",
                        kind="ANALYSIS_GAP",
                        test_id=pair.case.id,
                        build_mode=pair.build_mode,
                        summary=(
                            f"the {crash.version} build could not be executed "
                            f"for this input: {crash.message}"
                        ),
                        confidence="high",
                        evidence_refs=crash.evidence_refs,
                    )
                )

        return findings


def _is_fault(crash: CrashInfo) -> bool:
    """Whether this observation is a fault for comparison purposes."""
    return crash.outcome in ("security_event", "crash_unclassified")


def _describe(crash: CrashInfo) -> str:
    if not _is_fault(crash):
        if crash.outcome == "clean":
            return (
                f"no fault; {_terminated(crash)}"
                if crash.exit_code is not None
                else "no fault"
            )
        return f"{crash.outcome}: {crash.message}"
    where = f" at {crash.location}" if crash.location else ""
    return (
        f"{crash.error_type} detected by {crash.detection_mechanism}{where} "
        f"({_terminated(crash)})"
    )


def _terminated(crash: CrashInfo) -> str:
    if crash.timed_out:
        return "no exit within the timeout"
    if crash.signal_name:
        suffix = ", inferred" if crash.signal_inferred else ""
        return f"terminated by {crash.signal_name}{suffix}"
    return f"exit code {crash.exit_code}"


def _describe_behavior(result: ExecutionResult) -> str:
    if result.timed_out:
        termination = f"no exit within {result.timeout_s}s"
    elif result.signal is not None:
        termination = f"terminated by {result.signal_name}"
    else:
        termination = f"exit code {result.exit_code}"
    stdout = result.stdout_text()
    excerpt = stdout if len(stdout) <= 120 else stdout[:120] + "…"
    return f"{termination}, stdout {excerpt!r}"


def _same_observable_behavior(left: ExecutionResult, right: ExecutionResult) -> bool:
    """Whether two executions are indistinguishable on the functional axis.

    stderr is excluded: sanitizer banners and addresses differ between builds
    without the program behaving differently.
    """
    return (
        left.exit_code == right.exit_code
        and left.signal == right.signal
        and left.stdout == right.stdout
    )


_CONFIDENCE_RANK: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}


def _weakest(*values: Confidence) -> Confidence:
    return min(values, key=lambda value: _CONFIDENCE_RANK[value])
