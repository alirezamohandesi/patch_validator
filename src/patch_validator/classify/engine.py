"""Classification Engine — module 14 of the architecture.

Combines everything the run observed into three independent statuses and one
exit code.

The three axes — security, functional behaviour and completeness of the
analysis — are kept separate all the way to the end and all three survive into
the JSON report.  Only the final exit code collapses them, and it does so
through an explicit precedence rather than by one axis overwriting another
(SPEC 3.5, ADR-013).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from ..analysis.findings import Finding
from . import exit_codes

log = logging.getLogger(__name__)

SecurityStatus = Literal["CLEAN", "VULNERABLE", "UNKNOWN"]
FunctionalStatus = Literal["PASS", "REGRESSION", "UNKNOWN"]
CompletenessStatus = Literal["COMPLETE", "INCOMPLETE"]


@dataclass(frozen=True)
class MandatoryCheck:
    """One check that must have completed for a verdict to be trustworthy."""

    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class RunFacts:
    """Raw observations the classification is derived from."""

    findings: list[Finding] = field(default_factory=list)
    #: Non-empty when the target could not be built or configured.
    blocking_errors: list[str] = field(default_factory=list)
    expected_executions: int = 0
    completed_executions: int = 0
    #: True when at least one fault was observed on the base build.  Computed
    #: from evidence, not from any annotation on the test cases, so it stays
    #: valid for a patch the tool has never seen (R-SCOPE-09, ADR-012).
    base_fault_reproduced: bool = False
    #: Security findings whose replays did not agree with each other.
    unstable_finding_ids: list[str] = field(default_factory=list)
    #: Security findings that were never put through the correlation step.
    uncorrelated_finding_ids: list[str] = field(default_factory=list)
    hardening_analyzed: bool = False
    oracle_applicable_tests: int = 0
    sandbox_backend: str = ""
    sandbox_isolated: bool = True


@dataclass(frozen=True)
class Classification:
    security_status: SecurityStatus
    functional_status: FunctionalStatus
    completeness_status: CompletenessStatus
    final_classification: str
    exit_code: int
    mandatory_checks: tuple[MandatoryCheck, ...]
    rationale: tuple[str, ...]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "security_status": self.security_status,
            "functional_status": self.functional_status,
            "completeness_status": self.completeness_status,
            "final_classification": self.final_classification,
            "exit_code": self.exit_code,
            "exit_code_name": exit_codes.name(self.exit_code),
            "exit_code_meaning": exit_codes.EXIT_DESCRIPTIONS.get(self.exit_code, ""),
            "exit_code_precedence": list(exit_codes.EXIT_PRECEDENCE),
            "mandatory_checks": [check.to_dict() for check in self.mandatory_checks],
            "rationale": list(self.rationale),
            "counts": dict(self.counts),
        }


def classify(facts: RunFacts) -> Classification:
    """Derive the three statuses and the exit code from one run's facts."""
    checks = _mandatory_checks(facts)
    completeness: CompletenessStatus = (
        "COMPLETE" if all(check.passed for check in checks) else "INCOMPLETE"
    )

    confirmed, unconfirmed = _partition_security(facts.findings)
    regressions = [
        finding
        for finding in facts.findings
        if finding.axis == "functional"
        and finding.kind == "FUNCTIONAL_REGRESSION"
        and finding.authoritative
    ]
    functional_unknown = [
        finding
        for finding in facts.findings
        if finding.axis == "functional"
        and finding.kind == "INCONCLUSIVE"
        and finding.authoritative
    ]

    rationale: list[str] = []
    candidates: set[int] = set()

    if facts.blocking_errors:
        candidates.add(exit_codes.BUILD_OR_CONFIG_ERROR)
        rationale.extend(facts.blocking_errors)

    # -- security axis
    if confirmed:
        security: SecurityStatus = "VULNERABLE"
        candidates.add(exit_codes.VULN_REMAINS)
        for finding in confirmed:
            rationale.append(f"{finding.kind}: {finding.summary}")
    elif not facts.base_fault_reproduced:
        security = "UNKNOWN"
        candidates.add(exit_codes.INCONCLUSIVE)
        rationale.append(
            "no fault was reproduced on the base build, so there is nothing "
            "to show the patch fixed"
        )
    else:
        security = "CLEAN"
        rationale.append(
            "the fault reproduced on the base build is not observed on the "
            "patched build, and no other memory error was confirmed"
        )

    for finding in unconfirmed:
        candidates.add(exit_codes.INCONCLUSIVE)
        rationale.append(
            f"unconfirmed security observation on the patched build "
            f"({finding.test_id}/{finding.build_mode}): {finding.summary}"
        )

    # -- functional axis
    if regressions:
        functional: FunctionalStatus = "REGRESSION"
        candidates.add(exit_codes.FUNC_REGRESSION)
        for finding in regressions:
            rationale.append(f"FUNCTIONAL_REGRESSION: {finding.summary}")
    elif functional_unknown:
        functional = "UNKNOWN"
        candidates.add(exit_codes.INCONCLUSIVE)
        for finding in functional_unknown:
            rationale.append(f"functional comparison inconclusive: {finding.summary}")
    else:
        functional = "PASS"

    # -- completeness axis
    if completeness == "INCOMPLETE":
        candidates.add(exit_codes.INCONCLUSIVE)
        for check in checks:
            if not check.passed:
                rationale.append(f"mandatory check '{check.name}' failed: {check.detail}")

    exit_code = exit_codes.resolve(candidates)
    final = exit_codes.name(exit_code)

    counts = {
        "findings_total": len(facts.findings),
        "security_confirmed": len(confirmed),
        "security_unconfirmed": len(unconfirmed),
        "functional_regressions": len(regressions),
        "functional_inconclusive": len(functional_unknown),
        "fixed": sum(
            1 for finding in facts.findings if finding.kind == "FIXED"
        ),
        "completeness_gaps": sum(
            1 for finding in facts.findings if finding.axis == "completeness"
        ),
    }

    classification = Classification(
        security_status=security,
        functional_status=functional,
        completeness_status=completeness,
        final_classification=final,
        exit_code=exit_code,
        mandatory_checks=tuple(checks),
        rationale=tuple(rationale),
        counts=counts,
    )
    log.info(
        "classification: security=%s functional=%s completeness=%s -> %s (%d)",
        security,
        functional,
        completeness,
        final,
        exit_code,
    )
    return classification


def _partition_security(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split security problems into confirmed and merely observed.

    A stop that could not be classified is explicitly not enough to confirm a
    vulnerability (SPEC 3.5), so such a finding pushes the run towards
    inconclusive rather than towards exit code 10.
    """
    confirmed: list[Finding] = []
    unconfirmed: list[Finding] = []
    for finding in findings:
        if not finding.is_security_problem:
            continue
        crash = finding.patched_crash
        well_evidenced = (
            crash is not None
            and crash.outcome == "security_event"
            and crash.confidence in ("high", "medium")
        )
        (confirmed if well_evidenced else unconfirmed).append(finding)
    return confirmed, unconfirmed


def _mandatory_checks(facts: RunFacts) -> list[MandatoryCheck]:
    checks: list[MandatoryCheck] = []

    checks.append(
        MandatoryCheck(
            name="builds_succeeded",
            passed=not facts.blocking_errors,
            detail=(
                "; ".join(facts.blocking_errors)
                if facts.blocking_errors
                else "every configured build produced a binary"
            ),
        )
    )

    complete_matrix = (
        facts.expected_executions > 0
        and facts.completed_executions >= facts.expected_executions
    )
    checks.append(
        MandatoryCheck(
            name="full_matrix_executed",
            passed=complete_matrix,
            detail=(
                f"{facts.completed_executions}/{facts.expected_executions} "
                f"executions completed"
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="base_fault_reproduced",
            passed=facts.base_fault_reproduced,
            detail=(
                "a fault was observed on the base build"
                if facts.base_fault_reproduced
                else "no fault was observed on the base build for any input"
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="findings_reproducible",
            passed=not facts.unstable_finding_ids,
            detail=(
                "every confirmed finding replayed consistently"
                if not facts.unstable_finding_ids
                else "unstable: " + ", ".join(facts.unstable_finding_ids)
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="correlation_attempted",
            passed=not facts.uncorrelated_finding_ids,
            detail=(
                "every security finding was correlated against the diff"
                if not facts.uncorrelated_finding_ids
                else "not correlated: " + ", ".join(facts.uncorrelated_finding_ids)
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="hardening_analyzed",
            passed=facts.hardening_analyzed,
            detail=(
                "binary protections compared between both release builds"
                if facts.hardening_analyzed
                else "the hardening comparison did not run"
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="functional_oracle_available",
            passed=facts.oracle_applicable_tests > 0,
            detail=(
                f"{facts.oracle_applicable_tests} test case(s) carry an oracle"
                if facts.oracle_applicable_tests
                else "no test case defines an oracle, so functional behaviour "
                "was never checked"
            ),
        )
    )

    checks.append(
        MandatoryCheck(
            name="executions_isolated",
            passed=facts.sandbox_isolated,
            detail=(
                f"all executions ran under the '{facts.sandbox_backend}' sandbox"
                if facts.sandbox_isolated
                else f"executions ran under '{facts.sandbox_backend}', which "
                "provides no isolation"
            ),
        )
    )

    return checks
