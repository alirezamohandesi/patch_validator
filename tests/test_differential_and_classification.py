"""Differential comparison and final classification.

The specification asks for every meaningful combination of statuses to be
tested, so the decision tables are exercised exhaustively here rather than by
example.
"""

from __future__ import annotations

import itertools
import signal

import pytest

from conftest import (
    ASAN_STACK_OVERFLOW,
    ASAN_USE_AFTER_FREE,
    analyze,
    make_case,
    make_result,
)
from patch_validator.analysis.differential import CasePair, DifferentialTester
from patch_validator.analysis.findings import Finding
from patch_validator.analysis.oracle import OracleEvaluator
from patch_validator.classify import RunFacts, classify, exit_codes
from patch_validator.config.models import OutputMatcher

CLEAN = {"exit_code": 0, "stdout": b"ok\n"}
FAULT = {"exit_code": 1, "stderr": ASAN_STACK_OVERFLOW.encode()}
OTHER_FAULT = {"exit_code": 1, "stderr": ASAN_USE_AFTER_FREE.encode()}


def build_pair(case, base_kwargs, patched_kwargs, mode="sanitized"):
    base = make_result(
        test_id=case.id, version="base", build_mode=mode, **base_kwargs
    )
    patched = make_result(
        test_id=case.id, version="patched", build_mode=mode, **patched_kwargs
    )
    oracle = OracleEvaluator()
    return CasePair(
        case=case,
        build_mode=mode,  # type: ignore[arg-type]
        base_result=base,
        patched_result=patched,
        base_crash=analyze(base),
        patched_crash=analyze(patched),
        base_oracle=oracle.evaluate(case, base),
        patched_oracle=oracle.evaluate(case, patched),
    )


def kinds(findings: list[Finding], axis: str) -> list[str]:
    return [finding.kind for finding in findings if finding.axis == axis]


class TestSecurityAxis:
    def test_fault_disappears_is_fixed(self):
        pair = build_pair(make_case(with_oracle=False), FAULT, CLEAN)
        assert kinds(DifferentialTester().compare(pair), "security") == ["FIXED"]

    def test_fault_survives_is_an_incomplete_fix(self):
        pair = build_pair(make_case(with_oracle=False), FAULT, FAULT)
        findings = DifferentialTester().compare(pair)
        assert kinds(findings, "security") == ["INCOMPLETE_FIX"]
        assert findings[0].confidence == "high"
        assert not findings[0].signature_changed

    def test_fault_that_moves_is_still_incomplete_but_less_certain(self):
        pair = build_pair(make_case(with_oracle=False), FAULT, OTHER_FAULT)
        finding = DifferentialTester().compare(pair)[0]
        assert finding.kind == "INCOMPLETE_FIX"
        assert finding.signature_changed
        assert finding.confidence == "medium"

    def test_fault_only_on_patched_is_a_new_issue(self):
        pair = build_pair(make_case(with_oracle=False), CLEAN, FAULT)
        finding = DifferentialTester().compare(pair)[0]
        assert finding.kind == "NEW_ISSUE"
        assert any("does not by itself establish" in note for note in finding.notes)

    def test_no_fault_on_either_side_produces_nothing(self):
        pair = build_pair(make_case(with_oracle=False), CLEAN, CLEAN)
        assert kinds(DifferentialTester().compare(pair), "security") == []

    def test_timeout_goes_to_completeness_not_security(self):
        pair = build_pair(
            make_case(with_oracle=False),
            {"exit_code": None, "signal": 9, "timed_out": True},
            CLEAN,
        )
        findings = DifferentialTester().compare(pair)
        assert kinds(findings, "security") == []
        assert "RESOURCE_LIMIT" in kinds(findings, "completeness")


class TestFunctionalAxis:
    def _case(self):
        return make_case(
            "f",
            exit_code=0,
            stdout=OutputMatcher(match="exact", value="ok\n"),
        )

    def test_correct_then_broken_is_a_regression(self):
        pair = build_pair(
            self._case(), CLEAN, {"exit_code": 3, "stdout": b"wrong\n"}, mode="release"
        )
        findings = DifferentialTester().compare(pair)
        assert kinds(findings, "functional") == ["FUNCTIONAL_REGRESSION"]
        assert findings[0].authoritative

    def test_broken_then_correct_is_informational(self):
        pair = build_pair(self._case(), {"exit_code": 3, "stdout": b"x"}, CLEAN)
        assert kinds(DifferentialTester().compare(pair), "functional") == [
            "FUNCTIONAL_FIX"
        ]

    def test_identical_violation_on_both_sides_is_pre_existing(self):
        broken = {"exit_code": 3, "stdout": b"wrong\n"}
        pair = build_pair(self._case(), broken, broken)
        assert kinds(DifferentialTester().compare(pair), "functional") == [
            "PRE_EXISTING_DEFECT"
        ]

    def test_different_violations_on_both_sides_is_inconclusive(self):
        # The specification forbids calling this a regression: the base never
        # satisfied the oracle, so the patch cannot be shown to have broken it.
        pair = build_pair(
            self._case(),
            {"exit_code": 3, "stdout": b"wrong\n"},
            {"exit_code": 4, "stdout": b"different\n"},
        )
        finding = DifferentialTester().compare(pair)[0]
        assert finding.kind == "INCONCLUSIVE"
        assert finding.confidence == "low"

    def test_sanitized_functional_findings_are_not_authoritative(self):
        pair = build_pair(
            self._case(), CLEAN, {"exit_code": 3, "stdout": b"x"}, mode="sanitized"
        )
        assert not DifferentialTester().compare(pair)[0].authoritative

    def test_no_oracle_means_no_functional_finding_but_a_recorded_gap(self):
        pair = build_pair(make_case(with_oracle=False), CLEAN, CLEAN)
        findings = DifferentialTester().compare(pair)
        assert kinds(findings, "functional") == []
        assert "MISSING_ORACLE" in kinds(findings, "completeness")

    def test_a_crash_violates_an_exit_code_expectation(self):
        pair = build_pair(
            self._case(), CLEAN, {"exit_code": None, "signal": signal.SIGSEGV}
        )
        findings = DifferentialTester().compare(pair)
        # A segfault on the patched build is both a new memory error and a
        # violation of the behaviour the specification promises.
        assert kinds(findings, "security") == ["NEW_ISSUE"]
        functional = [f for f in findings if f.axis == "functional"]
        assert [f.kind for f in functional] == ["FUNCTIONAL_REGRESSION"]
        failure = functional[0].patched_oracle.failures()[0]
        assert "SIGSEGV" in failure.observed


class TestPairIntegrity:
    def test_mixing_build_modes_is_refused(self):
        case = make_case(with_oracle=False)
        base = make_result(version="base", build_mode="release")
        patched = make_result(version="patched", build_mode="sanitized")
        with pytest.raises(ValueError, match="different build modes"):
            CasePair(
                case=case,
                build_mode="release",
                base_result=base,
                patched_result=patched,
                base_crash=analyze(base),
                patched_crash=analyze(patched),
                base_oracle=OracleEvaluator().evaluate(case, base),
                patched_oracle=OracleEvaluator().evaluate(case, patched),
            )

    def test_two_base_results_are_refused(self):
        case = make_case(with_oracle=False)
        one = make_result(version="base")
        two = make_result(version="base")
        with pytest.raises(ValueError, match="one base and one patched"):
            CasePair(
                case=case,
                build_mode="sanitized",
                base_result=one,
                patched_result=two,
                base_crash=analyze(one),
                patched_crash=analyze(two),
                base_oracle=OracleEvaluator().evaluate(case, one),
                patched_oracle=OracleEvaluator().evaluate(case, two),
            )


def healthy_facts(**overrides) -> RunFacts:
    defaults = {
        "findings": [],
        "blocking_errors": [],
        "expected_executions": 8,
        "completed_executions": 8,
        "base_fault_reproduced": True,
        "unstable_finding_ids": [],
        "uncorrelated_finding_ids": [],
        "hardening_analyzed": True,
        "oracle_applicable_tests": 4,
        "sandbox_backend": "bubblewrap",
        "sandbox_isolated": True,
    }
    return RunFacts(**{**defaults, **overrides})


def security_finding(kind="INCOMPLETE_FIX", confidence="high", outcome="security_event"):
    patched = make_result(
        version="patched",
        exit_code=1,
        stderr=ASAN_STACK_OVERFLOW.encode() if outcome == "security_event" else b"",
        signal=None if outcome == "security_event" else signal.SIGUSR1,
    )
    crash = analyze(patched)
    return Finding(
        id=f"sec/{kind}",
        axis="security",
        kind=kind,  # type: ignore[arg-type]
        test_id="t",
        build_mode="sanitized",
        summary="x",
        confidence=confidence,  # type: ignore[arg-type]
        patched_crash=crash,
    )


def functional_finding(kind="FUNCTIONAL_REGRESSION", authoritative=True):
    return Finding(
        id=f"func/{kind}",
        axis="functional",
        kind=kind,  # type: ignore[arg-type]
        test_id="t",
        build_mode="release",
        summary="x",
        authoritative=authoritative,
    )


class TestClassification:
    def test_clean_run_passes(self):
        result = classify(healthy_facts())
        assert result.exit_code == exit_codes.PASS
        assert (result.security_status, result.functional_status) == ("CLEAN", "PASS")
        assert result.completeness_status == "COMPLETE"

    def test_surviving_vulnerability_gives_ten(self):
        result = classify(healthy_facts(findings=[security_finding()]))
        assert result.exit_code == exit_codes.VULN_REMAINS
        assert result.security_status == "VULNERABLE"

    def test_functional_regression_gives_twenty(self):
        result = classify(healthy_facts(findings=[functional_finding()]))
        assert result.exit_code == exit_codes.FUNC_REGRESSION
        assert result.functional_status == "REGRESSION"

    def test_build_error_gives_thirty(self):
        result = classify(healthy_facts(blocking_errors=["build of base failed"]))
        assert result.exit_code == exit_codes.BUILD_OR_CONFIG_ERROR

    def test_unreproduced_base_fault_gives_forty_not_pass(self):
        result = classify(healthy_facts(base_fault_reproduced=False))
        assert result.exit_code == exit_codes.INCONCLUSIVE
        assert result.security_status == "UNKNOWN"

    def test_unstable_finding_blocks_completeness(self):
        result = classify(healthy_facts(unstable_finding_ids=["sec/a"]))
        assert result.completeness_status == "INCOMPLETE"
        assert result.exit_code == exit_codes.INCONCLUSIVE

    def test_unisolated_execution_blocks_completeness(self):
        result = classify(
            healthy_facts(sandbox_backend="subprocess", sandbox_isolated=False)
        )
        assert result.completeness_status == "INCOMPLETE"
        assert result.exit_code == exit_codes.INCONCLUSIVE

    def test_partial_matrix_blocks_completeness(self):
        result = classify(healthy_facts(completed_executions=5))
        assert result.completeness_status == "INCOMPLETE"

    def test_uncorrelated_security_finding_blocks_completeness(self):
        result = classify(healthy_facts(uncorrelated_finding_ids=["sec/a"]))
        assert result.completeness_status == "INCOMPLETE"

    def test_missing_hardening_blocks_completeness(self):
        assert classify(healthy_facts(hardening_analyzed=False)).completeness_status == (
            "INCOMPLETE"
        )

    def test_unclassified_stop_does_not_confirm_a_vulnerability(self):
        # "یک توقف طبقه‌بندی‌نشده به‌تنهایی برای تأیید آسیب‌پذیری کافی نیست"
        finding = security_finding(outcome="unclassified")
        result = classify(healthy_facts(findings=[finding]))
        assert result.exit_code == exit_codes.INCONCLUSIVE
        assert result.counts["security_unconfirmed"] == 1
        assert result.counts["security_confirmed"] == 0

    def test_non_authoritative_regression_does_not_decide_the_run(self):
        result = classify(
            healthy_facts(findings=[functional_finding(authoritative=False)])
        )
        assert result.exit_code == exit_codes.PASS

    @pytest.mark.parametrize(
        ("candidates", "expected"),
        [
            ({0}, 0),
            ({10}, 10),
            ({20}, 20),
            ({30}, 30),
            ({40}, 40),
            ({10, 20}, 10),
            ({20, 40}, 20),
            ({10, 40}, 10),
            ({30, 10}, 30),
            ({30, 10, 20, 40, 0}, 30),
            ({10, 20, 40, 0}, 10),
            ({20, 40, 0}, 20),
            ({40, 0}, 40),
            (set(), 0),
        ],
    )
    def test_exit_precedence(self, candidates, expected):
        assert exit_codes.resolve(candidates) == expected

    def test_precedence_follows_the_official_specification(self):
        assert exit_codes.EXIT_PRECEDENCE == (30, 10, 20, 40, 0)

    def test_every_status_combination_produces_a_defined_code(self):
        """No combination of axes may fall through to an undefined result."""
        options = [
            [[], [security_finding()], [security_finding(outcome="unclassified")]],
            [[], [functional_finding()], [functional_finding("INCONCLUSIVE")]],
            [True, False],
            [True, False],
        ]
        for security, functional, reproduced, isolated in itertools.product(*options):
            result = classify(
                healthy_facts(
                    findings=[*security, *functional],
                    base_fault_reproduced=reproduced,
                    sandbox_isolated=isolated,
                    sandbox_backend="bubblewrap" if isolated else "subprocess",
                )
            )
            assert result.exit_code in exit_codes.EXIT_PRECEDENCE
            assert result.final_classification == exit_codes.name(result.exit_code)
            # A confirmed vulnerability always outranks everything but a
            # broken build, whatever else the run observed.
            if security and security[0].patched_crash.outcome == "security_event":
                assert result.exit_code == exit_codes.VULN_REMAINS
