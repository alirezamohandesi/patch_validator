"""Re-run generated regression tests.

A generated test is only worth something if it runs again later.  This module
replays a previously generated suite against a fresh pair of builds and checks
the three conditions the generator recorded, so a suite produced by one run can
gate every run after it (R-REG-04).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..analysis.crash import CrashAnalyzer, CrashInfo
from ..analysis.oracle import OracleEvaluator
from ..build import BuildRecord
from ..config import (
    BuildMode,
    OracleSpec,
    OutputMatcher,
    TestCase,
    ValidationConfig,
    Version,
)
from ..errors import ConfigError
from ..execution import ExecutionEngine

log = logging.getLogger(__name__)

Outcome = Literal["pass", "security_failure", "functional_failure", "stale"]


@dataclass(frozen=True)
class CheckOutcome:
    """Result of replaying one generated regression test."""

    case_id: str
    outcome: Outcome
    base_faulted: bool
    patched_faulted: bool
    oracle_verdict: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.outcome == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "outcome": self.outcome,
            "base_faulted": self.base_faulted,
            "patched_faulted": self.patched_faulted,
            "oracle_verdict": self.oracle_verdict,
            "detail": self.detail,
        }


def load_suite(path: Path) -> tuple[list[dict[str, Any]], Path]:
    """Load a generated suite and the run directory its paths are relative to."""
    if not path.is_file():
        raise ConfigError(f"regression suite not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: not valid JSON: {exc}") from exc

    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ConfigError(f"{path}: no 'cases' array")
    # suite.json lives at <run>/regression/suite.json and its refs are
    # relative to <run>.
    return cases, path.parent.parent


class RegressionRunner:
    """Replays generated regression tests against a pair of builds."""

    def __init__(
        self,
        config: ValidationConfig,
        engine: ExecutionEngine,
        analyzer: CrashAnalyzer,
    ) -> None:
        self.config = config
        self.engine = engine
        self.analyzer = analyzer
        self.oracle = OracleEvaluator()

    def check(
        self,
        case: dict[str, Any],
        run_root: Path,
        builds: dict[tuple[Version, BuildMode], BuildRecord],
    ) -> CheckOutcome:
        case_id = case["id"]
        expectations = case["expectations"]
        mode: BuildMode = expectations.get("build_mode", "sanitized")

        data = self._read_input(case, run_root)
        test_case = self._rebuild_test_case(case, data)

        base = self._observe(test_case, builds[("base", mode)])
        patched = self._observe(test_case, builds[("patched", mode)])

        expected_signature = expectations["base"]["location_signature"]

        # 1. The base build must still fault, otherwise the test guards
        #    nothing and silently passing would be misleading.
        if not _faulted(base):
            return CheckOutcome(
                case_id=case_id,
                outcome="stale",
                base_faulted=False,
                patched_faulted=_faulted(patched),
                oracle_verdict="not evaluated",
                detail=(
                    "the base build no longer faults on this input, so the test "
                    "no longer guards anything; regenerate it"
                ),
            )
        if base.location_signature != expected_signature:
            return CheckOutcome(
                case_id=case_id,
                outcome="stale",
                base_faulted=True,
                patched_faulted=_faulted(patched),
                oracle_verdict="not evaluated",
                detail=(
                    f"the base build faults differently now: expected "
                    f"{expected_signature[:12]}, observed "
                    f"{base.location_signature[:12]} ({base.error_type})"
                ),
            )

        # 2. The patched build must not fault.
        if _faulted(patched):
            return CheckOutcome(
                case_id=case_id,
                outcome="security_failure",
                base_faulted=True,
                patched_faulted=True,
                oracle_verdict="not evaluated",
                detail=(
                    f"{patched.error_type} still reproduces on the patched build "
                    f"at {patched.location or 'an unknown location'}"
                ),
            )

        # 3. The patched build must behave as the specification requires.
        #    Without this, a change that exits before reaching the parser
        #    would satisfy the first two checks while breaking the program.
        if test_case.oracle is None:
            return CheckOutcome(
                case_id=case_id,
                outcome="pass",
                base_faulted=True,
                patched_faulted=False,
                oracle_verdict="none defined",
                detail="fault present on base, absent on patched; no oracle to check",
            )

        verdict = self.oracle.evaluate(
            test_case, self._last_result(test_case, builds[("patched", mode)])
        )
        if not verdict.matched:
            return CheckOutcome(
                case_id=case_id,
                outcome="functional_failure",
                base_faulted=True,
                patched_faulted=False,
                oracle_verdict=verdict.verdict,
                detail=f"the patched build violates the oracle: {verdict.describe()}",
            )

        return CheckOutcome(
            case_id=case_id,
            outcome="pass",
            base_faulted=True,
            patched_faulted=False,
            oracle_verdict=verdict.verdict,
            detail="fault present on base, absent on patched, oracle satisfied",
        )

    # -- helpers -----------------------------------------------------------

    def _read_input(self, case: dict[str, Any], run_root: Path) -> bytes:
        reference = case.get("input_ref", "")
        path = (run_root / reference).resolve()
        if not path.is_file():
            raise ConfigError(
                f"regression case '{case['id']}': input not found at {path}",
                remedy="the suite must be read from the run directory that produced it",
            )
        return path.read_bytes()

    def _rebuild_test_case(self, case: dict[str, Any], data: bytes) -> TestCase:
        """Reconstruct an executable test case from the stored definition."""
        stored = case.get("test_case", {})
        oracle_spec = stored.get("oracle")
        oracle = None
        if oracle_spec:
            oracle = OracleSpec(
                source=oracle_spec["source"],
                input_validity=oracle_spec["input_validity"],
                exit_code=oracle_spec.get("exit_code"),
                stdout=_matcher(oracle_spec.get("stdout")),
                stderr=_matcher(oracle_spec.get("stderr")),
                semantics=oracle_spec.get("semantics", ""),
                instructor_approved=oracle_spec.get("instructor_approved", "pending"),
            )
        return TestCase(
            id=case["id"],
            category="security",
            input_inline=data,
            oracle=oracle,
            note=stored.get("note", ""),
        )

    def _observe(self, case: TestCase, build: BuildRecord) -> CrashInfo:
        self._cache: dict[tuple[str, str], Any] = getattr(self, "_cache", {})
        result = self.engine.run_case(
            case, build, artifact_prefix=f"regression-run/{case.id}/{build.version}"
        )
        self._cache[(case.id, build.version)] = result
        return self.analyzer.analyze(result)

    def _last_result(self, case: TestCase, build: BuildRecord):
        return self._cache[(case.id, build.version)]


def _faulted(crash: CrashInfo) -> bool:
    return crash.outcome in ("security_event", "crash_unclassified")


def _matcher(raw: dict[str, Any] | None) -> OutputMatcher:
    if raw is None:
        return OutputMatcher()
    return OutputMatcher(match=raw["match"], value=raw.get("value", ""))
