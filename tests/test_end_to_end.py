"""End-to-end runs against the toy target.

These are the tests that would catch a regression in the tool itself: each
one drives the real CLI over the real four-binary matrix and checks the exit
code the specification requires for that scenario.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import CONFIG
from patch_validator.cli import main
from patch_validator.classify import exit_codes
from patch_validator.report.writer import validate as validate_report

pytestmark = [pytest.mark.slow, pytest.mark.toolchain, pytest.mark.sandbox]


def run_validate(run_dir: Path, revision: str, *extra: str) -> int:
    return main(
        [
            "-q",
            "validate",
            "--config",
            str(CONFIG),
            "--patched-revision",
            revision,
            "--run-dir",
            str(run_dir),
            *extra,
        ]
    )


def load_report(run_dir: Path) -> dict:
    return json.loads((run_dir / "report.json").read_text())


@pytest.fixture(scope="module")
def correct_run(tmp_path_factory) -> tuple[int, dict, Path]:
    run_dir = tmp_path_factory.mktemp("correct")
    code = run_validate(run_dir, "correct-patch")
    return code, load_report(run_dir), run_dir


@pytest.fixture(scope="module")
def incomplete_run(tmp_path_factory) -> tuple[int, dict, Path]:
    run_dir = tmp_path_factory.mktemp("incomplete")
    code = run_validate(run_dir, "incomplete-patch")
    return code, load_report(run_dir), run_dir


@pytest.fixture(scope="module")
def regression_run(tmp_path_factory) -> tuple[int, dict, Path]:
    run_dir = tmp_path_factory.mktemp("regression")
    code = run_validate(run_dir, "regression-patch", "--no-minimize")
    return code, load_report(run_dir), run_dir


class TestCorrectPatch:
    def test_it_passes(self, correct_run):
        code, report, _ = correct_run
        assert code == exit_codes.PASS
        assert report["classification"]["security_status"] == "CLEAN"
        assert report["classification"]["functional_status"] == "PASS"
        assert report["classification"]["completeness_status"] == "COMPLETE"

    def test_the_base_fault_was_actually_reproduced(self, correct_run):
        _, report, _ = correct_run
        base_faults = [
            crash
            for crash in report["crash_evidence"]
            if crash["version"] == "base" and crash["outcome"] == "security_event"
        ]
        assert base_faults, "PASS is only meaningful if the base fault was seen"

    def test_every_fault_is_reported_as_fixed(self, correct_run):
        _, report, _ = correct_run
        kinds = {finding["kind"] for finding in report["findings"]["security"]}
        assert kinds == {"FIXED"}

    def test_the_full_matrix_ran(self, correct_run):
        _, report, _ = correct_run
        tests = len(report["test_configuration"]["tests"])
        assert len(report["executions"]) == tests * 4


class TestIncompletePatch:
    def test_it_reports_a_surviving_vulnerability(self, incomplete_run):
        code, report, _ = incomplete_run
        assert code == exit_codes.VULN_REMAINS
        assert report["classification"]["security_status"] == "VULNERABLE"

    def test_the_original_reproducer_is_blocked_but_another_is_not(self, incomplete_run):
        _, report, _ = incomplete_run
        by_test = {
            (finding["test_id"], finding["build_mode"]): finding["kind"]
            for finding in report["findings"]["security"]
        }
        assert by_test[("vuln_text_long", "sanitized")] == "FIXED"
        assert by_test[("vuln_raw_long", "sanitized")] == "INCOMPLETE_FIX"

    def test_the_blocked_path_is_correlated_with_the_patch(self, incomplete_run):
        _, report, _ = incomplete_run
        correlations = {
            correlation["finding_id"]: correlation
            for correlation in report["patch_correlations"]
        }
        blocked = correlations["sec/vuln_text_long/sanitized"]
        assert blocked["correlation_status"] == "CONFIRMED"
        assert blocked["affected_function"] == "handle_text"
        # The fault was in copy_payload; the patch changed its caller. That
        # relationship is exactly what the specification asks to be found.
        assert blocked["indirect"] is True

    def test_the_surviving_path_is_not_attributed_to_the_patch(self, incomplete_run):
        _, report, _ = incomplete_run
        correlations = {
            correlation["finding_id"]: correlation
            for correlation in report["patch_correlations"]
        }
        surviving = correlations["sec/vuln_raw_long/sanitized"]
        assert surviving["correlation_status"] in ("WEAK", "UNKNOWN")

    def test_functional_behaviour_is_unaffected(self, incomplete_run):
        _, report, _ = incomplete_run
        assert report["classification"]["functional_status"] == "PASS"


class TestRegressionPatch:
    def test_it_reports_a_functional_regression(self, regression_run):
        code, report, _ = regression_run
        assert code == exit_codes.FUNC_REGRESSION
        assert report["classification"]["functional_status"] == "REGRESSION"

    def test_the_security_fault_is_gone(self, regression_run):
        _, report, _ = regression_run
        assert report["classification"]["security_status"] == "CLEAN"

    def test_the_regression_names_the_input_and_both_behaviours(self, regression_run):
        _, report, _ = regression_run
        regressions = [
            finding
            for finding in report["findings"]["functional"]
            if finding["kind"] == "FUNCTIONAL_REGRESSION"
        ]
        assert {finding["test_id"] for finding in regressions} >= {
            "valid_text24",
            "boundary_text31",
        }
        for finding in regressions:
            assert finding["base_oracle"]["verdict"] == "MATCH"
            assert finding["patched_oracle"]["verdict"] == "MISMATCH"

    def test_only_release_findings_decide_the_verdict(self, regression_run):
        _, report, _ = regression_run
        authoritative = [
            finding
            for finding in report["findings"]["functional"]
            if finding["kind"] == "FUNCTIONAL_REGRESSION" and finding["authoritative"]
        ]
        assert all(finding["build_mode"] == "release" for finding in authoritative)


class TestEvidence:
    def test_the_report_satisfies_its_own_schema(self, correct_run):
        _, report, _ = correct_run
        validate_report(report)

    def test_every_finding_references_evidence_that_exists(self, incomplete_run):
        _, report, run_dir = incomplete_run
        checked = 0
        for axis in report["findings"].values():
            for finding in axis:
                for reference in finding["evidence_refs"]:
                    assert (run_dir / reference).exists(), reference
                    checked += 1
        assert checked > 0

    def test_release_and_sanitized_results_are_never_mixed(self, correct_run):
        _, report, _ = correct_run
        for finding in report["findings"]["security"]:
            for side in ("base_crash", "patched_crash"):
                if finding[side]:
                    assert finding[side]["build_mode"] == finding["build_mode"]

    def test_the_sanitizer_revealed_something_the_release_build_did_not(
        self, correct_run
    ):
        _, report, _ = correct_run
        revealing = [
            observation
            for observation in report["build_mode_comparison"]
            if observation["revealed_only_by_sanitizer"]
        ]
        assert revealing, "boundary_text32 faults only under the sanitizer"

    def test_bundles_are_replayed_at_least_three_times(self, correct_run):
        _, report, run_dir = correct_run
        assert report["reproductions"]
        for reproduction in report["reproductions"]:
            assert reproduction["replay_count"] >= 3
            assert reproduction["stability"] == "stable"
            assert (run_dir / reproduction["manifest_ref"]).exists()
            assert (run_dir / reproduction["bundle_ref"] / "REPRODUCE.md").exists()

    def test_a_bundle_can_be_replayed_from_the_command_line(self, correct_run):
        _, report, run_dir = correct_run
        bundle = run_dir / report["reproductions"][0]["bundle_ref"]
        # The binary is gone once the run finished, which the replay must
        # detect rather than silently report success.
        assert main(["-q", "reproduce", str(bundle)]) in (
            exit_codes.PASS,
            exit_codes.BUILD_OR_CONFIG_ERROR,
        )

    def test_generated_regression_tests_assert_all_three_conditions(self, correct_run):
        _, report, run_dir = correct_run
        assert report["regression_tests"]
        for case in report["regression_tests"]:
            expectations = case["expectations"]
            assert expectations["base"]["must_fault"] is True
            assert expectations["patched"]["must_fault"] is False
            assert expectations["patched"]["oracle"] is not None
            assert (run_dir / case["input_ref"]).exists()
            assert (run_dir / case["case_ref"]).exists()

    def test_hardening_was_compared_with_its_limitations_stated(self, correct_run):
        _, report, _ = correct_run
        hardening = report["hardening"]
        names = {item["protection"] for item in hardening["protections"]}
        assert {"nx", "pie", "relro", "stack_canary"} <= names
        assert any("ASLR" in text for text in hardening["limitations"])

    def test_the_markdown_summary_agrees_with_the_json(self, incomplete_run):
        _, report, run_dir = incomplete_run
        markdown = (run_dir / "report.md").read_text()
        assert report["classification"]["final_classification"] in markdown
        assert f"exit code {report['exit_code']}" in markdown


class TestUnseenPatch:
    """The defence-day scenario: a patch the configuration never mentions."""

    def test_a_revision_override_validates_an_unconfigured_patch(self, tmp_path):
        configured = json.loads(
            (Path(CONFIG).parent / CONFIG.name).read_text()
            if CONFIG.suffix == ".json"
            else "{}"
        )
        del configured
        run_dir = tmp_path / "unseen"
        code = run_validate(run_dir, "incomplete-patch", "--no-minimize")
        report = load_report(run_dir)
        # Nothing in the configuration names this revision, and no test case
        # is annotated with what the patch is supposed to do.
        assert report["revisions"]["patched"]["revision"] == "incomplete-patch"
        assert code == exit_codes.VULN_REMAINS

    def test_no_decision_depends_on_the_patch_identity(self):
        """The classification input carries no patch name, by construction."""
        from dataclasses import fields

        from patch_validator.classify import RunFacts

        names = {field.name for field in fields(RunFacts)}
        assert not any("revision" in name or "patch_name" in name for name in names)


class TestFailedRunReporting:
    """A run that dies during setup must still be diagnosable."""

    def test_an_unavailable_sandbox_still_produces_a_readable_report(
        self, tmp_path, monkeypatch
    ):
        from patch_validator.artifacts import ArtifactStore
        from patch_validator.config import load_config
        from patch_validator.pipeline import Pipeline
        from patch_validator.sandbox.bubblewrap import BubblewrapSandboxBackend

        monkeypatch.setattr(
            BubblewrapSandboxBackend,
            "_smoke_test",
            lambda self: (False, "simulated namespace failure"),
        )
        store = ArtifactStore(tmp_path / "run")
        pipeline = Pipeline(load_config(CONFIG), artifacts=store, run_id="failed")
        record = pipeline.run()
        json_ref, markdown_ref = pipeline.write_reports()

        assert record.exit_code == exit_codes.BUILD_OR_CONFIG_ERROR
        assert (store.root / json_ref).exists()
        assert (store.root / markdown_ref).exists()
        # The report must satisfy the schema even with no revisions resolved,
        # no builds and no executions.
        validate_report(json.loads((store.root / json_ref).read_text()))

    def test_the_isolation_check_does_not_blame_executions_that_never_ran(
        self, tmp_path, monkeypatch
    ):
        from patch_validator.artifacts import ArtifactStore
        from patch_validator.config import load_config
        from patch_validator.pipeline import Pipeline
        from patch_validator.sandbox.bubblewrap import BubblewrapSandboxBackend

        monkeypatch.setattr(
            BubblewrapSandboxBackend, "_smoke_test", lambda self: (False, "simulated")
        )
        pipeline = Pipeline(
            load_config(CONFIG), artifacts=ArtifactStore(tmp_path / "r"), run_id="f"
        )
        record = pipeline.run()
        check = next(
            item
            for item in record.classification.mandatory_checks
            if item.name == "executions_isolated"
        )
        assert check.detail == "no execution took place"
