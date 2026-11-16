"""Independent functional oracle — module 7 of the architecture.

Checks an execution against the behaviour the target's *specification*
promises, never against the behaviour the patched build happens to produce.
That independence is the only thing that makes a functional-regression claim
defensible: if the oracle were derived from the patched build, the patched
build could not possibly be found wrong (SPEC 2, ADR-006).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from ..config import OracleSpec, OutputMatcher, TestCase
from ..execution import ExecutionResult

log = logging.getLogger(__name__)

Verdict = Literal["MATCH", "MISMATCH", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class CheckResult:
    """One expectation and what was actually observed."""

    name: str
    passed: bool
    expected: str
    observed: str

    def describe(self) -> str:
        if self.passed:
            return f"{self.name}: {self.observed} as expected"
        return f"{self.name}: expected {self.expected}, observed {self.observed}"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class OracleVerdict:
    test_id: str
    version: str
    build_mode: str
    verdict: Verdict
    checks: tuple[CheckResult, ...] = ()
    oracle_source: str = ""
    instructor_approved: str = "pending"
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.verdict == "MATCH"

    @property
    def applicable(self) -> bool:
        return self.verdict != "NOT_APPLICABLE"

    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def describe(self) -> str:
        if self.verdict == "NOT_APPLICABLE":
            return f"no oracle defined ({self.reason})" if self.reason else "no oracle"
        if self.matched:
            return "matches the specification"
        return "; ".join(check.describe() for check in self.failures())

    def to_dict(self) -> dict[str, object]:
        return {
            "test_id": self.test_id,
            "version": self.version,
            "build_mode": self.build_mode,
            "verdict": self.verdict,
            "oracle_source": self.oracle_source,
            "instructor_approved": self.instructor_approved,
            "reason": self.reason,
            "checks": [check.to_dict() for check in self.checks],
        }


class OracleEvaluator:
    """Compares observed behaviour against the specified behaviour."""

    def evaluate(self, case: TestCase, result: ExecutionResult) -> OracleVerdict:
        if case.oracle is None:
            return OracleVerdict(
                test_id=case.id,
                version=result.version,
                build_mode=result.build_mode,
                verdict="NOT_APPLICABLE",
                reason="the test case defines no oracle",
            )

        oracle = case.oracle
        checks: list[CheckResult] = []
        checks.append(_check_termination(oracle, result))
        checks.append(
            _check_stream("stdout", oracle.stdout, result.stdout_text())
        )
        checks.append(
            _check_stream("stderr", oracle.stderr, result.stderr_text())
        )
        checks = [check for check in checks if check is not None]

        passed = all(check.passed for check in checks)
        return OracleVerdict(
            test_id=case.id,
            version=result.version,
            build_mode=result.build_mode,
            verdict="MATCH" if passed else "MISMATCH",
            checks=tuple(checks),
            oracle_source=oracle.source,
            instructor_approved=oracle.instructor_approved,
        )


def _check_termination(oracle: OracleSpec, result: ExecutionResult) -> CheckResult:
    """Exit code check, with signal termination treated as its own failure.

    A specification that promises "exits with code 2" is violated just as
    much by a crash as by the wrong code, but the two need to read
    differently in the report.
    """
    if oracle.exit_code is None:
        return CheckResult(
            name="termination",
            passed=True,
            expected="unspecified",
            observed=_describe_termination(result),
        )

    expected = f"exit code {oracle.exit_code}"
    observed = _describe_termination(result)

    if result.timed_out:
        return CheckResult("termination", False, expected, observed)
    if result.signal is not None:
        return CheckResult("termination", False, expected, observed)
    return CheckResult(
        name="termination",
        passed=result.exit_code == oracle.exit_code,
        expected=expected,
        observed=observed,
    )


def _describe_termination(result: ExecutionResult) -> str:
    if result.timed_out:
        return f"no exit within {result.timeout_s}s"
    if result.signal is not None:
        suffix = " (inferred)" if result.signal_inferred else ""
        return f"terminated by {result.signal_name}{suffix}"
    return f"exit code {result.exit_code}"


def _check_stream(name: str, matcher: OutputMatcher, observed: str) -> CheckResult | None:
    if matcher.match == "ignore":
        return None

    if matcher.match == "absent":
        return CheckResult(
            name=name,
            passed=observed == "",
            expected="no output",
            observed=_excerpt(observed) if observed else "no output",
        )

    if matcher.match == "exact":
        return CheckResult(
            name=name,
            passed=observed == matcher.value,
            expected=_excerpt(matcher.value),
            observed=_excerpt(observed),
        )

    if matcher.match == "contains":
        return CheckResult(
            name=name,
            passed=matcher.value in observed,
            expected=f"containing {_excerpt(matcher.value)}",
            observed=_excerpt(observed),
        )

    # regex
    try:
        pattern = re.compile(matcher.value, re.MULTILINE | re.DOTALL)
    except re.error as exc:  # pragma: no cover - config is schema-checked
        return CheckResult(
            name=name,
            passed=False,
            expected=f"matching {matcher.value!r}",
            observed=f"invalid oracle pattern: {exc}",
        )
    return CheckResult(
        name=name,
        passed=pattern.search(observed) is not None,
        expected=f"matching {matcher.value!r}",
        observed=_excerpt(observed),
    )


def _excerpt(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return repr(text)
    return repr(text[:limit] + "…")
