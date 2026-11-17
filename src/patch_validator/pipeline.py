"""Pipeline — module 16 of the architecture.

Orchestrates one full validation run and assembles the run record.  All the
decision logic lives in the modules below; this file decides only *what runs
in which order* and how the pieces are wired together.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .analysis.crash import CrashAnalyzer, CrashInfo
from .analysis.differential import CasePair, DifferentialTester
from .analysis.findings import Finding
from .analysis.hardening import HardeningAnalyzer
from .analysis.oracle import OracleEvaluator
from .analysis.patch import PatchAnalyzer
from .artifacts import ArtifactStore, new_run_id
from .build import BuildManager, BuildRecord
from .classify import RunFacts, classify
from .config import BuildMode, TestCase, ValidationConfig, Version
from .errors import BuildError, PatchValidatorError
from .execution import ExecutionEngine, ExecutionResult
from .minimize import Minimizer
from .regression.generator import RegressionGenerator
from .report.model import BuildModeObservation, RunRecord
from .report import writer
from .reproducer import ReproducerManager
from .sandbox import SandboxManager
from .util import environment
from .vcs import GitRepo

log = logging.getLogger(__name__)


class Pipeline:
    """Runs every stage of a validation and produces the report."""

    def __init__(
        self,
        config: ValidationConfig,
        *,
        artifacts: ArtifactStore | None = None,
        workspace: Path | None = None,
        command: list[str] | None = None,
        run_id: str | None = None,
        keep_workspace: bool = False,
    ) -> None:
        self.config = config
        self.run_id = run_id or new_run_id()
        self.artifacts = artifacts or ArtifactStore(Path("runs") / self.run_id)
        self._owns_workspace = workspace is None
        self.workspace = workspace or Path(
            tempfile.mkdtemp(prefix=f"patch-validator-{self.run_id}-")
        )
        self.keep_workspace = keep_workspace
        self.command = command or []

        self.record = RunRecord(
            run_id=self.run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            config=config,
            command=self.command,
        )

    # -- orchestration -----------------------------------------------------

    def run(self) -> RunRecord:
        started = time.monotonic()
        sandbox = SandboxManager(self.config.sandbox)
        repo = GitRepo(self.config.target.repo_path)
        builder = BuildManager(self.config, repo, self.workspace, self.artifacts)
        blocking: list[str] = []

        self.record.environment = environment.capture()
        # Populated before anything can fail so that a run which dies during
        # setup still produces a schema-valid report.  A pipeline that cannot
        # read the report of a failed run cannot diagnose it (R-CICD-07).
        self.record.sandbox = {
            "backend": self.config.sandbox.backend,
            "isolated": False,
            "probe": {},
        }

        try:
            probe = sandbox.ensure_available()
            self.record.sandbox = {
                "backend": sandbox.backend_name,
                "isolated": sandbox.backend_name != "subprocess",
                "probe": probe.to_dict(),
            }

            builder.prepare_sources()
            self.record.commits = {
                "base": builder.commit_info("base"),
                "patched": builder.commit_info("patched"),
            }
            builds = builder.build_all()
            self.record.builds = list(builds.values())

            analyzer = CrashAnalyzer(
                source_roots=(
                    builder.source_path("base"),
                    builder.source_path("patched"),
                )
            )
            engine = ExecutionEngine(
                self.config, sandbox, self.workspace, self.artifacts
            )
            patch_analyzer = PatchAnalyzer(
                repo,
                self.config.target.base_revision,
                self.config.target.patched_revision,
            )
            writer.write_patch_diff(patch_analyzer.diff.raw, self.artifacts)
            self.record.patch_summary = {
                **patch_analyzer.diff.to_dict(),
                "changed_functions": {
                    path: sorted(names)
                    for path, names in patch_analyzer.changed_functions().items()
                },
                "diff_ref": "patch.diff",
            }

            pairs = self._execute_matrix(engine, analyzer, builds)
            self._derive_findings(pairs, patch_analyzer)
            self._observe_build_modes(pairs)
            self._reproduce_and_minimize(engine, analyzer, builds, pairs)
            self._analyze_hardening(builds)

        except BuildError as exc:
            blocking.append(str(exc))
            log.error("%s", exc)
            if exc.remedy:
                log.error("hint: %s", exc.remedy)
        except PatchValidatorError as exc:
            blocking.append(str(exc))
            log.error("%s", exc)
            if exc.remedy:
                log.error("hint: %s", exc.remedy)
        finally:
            builder.cleanup()
            if self._owns_workspace and not self.keep_workspace:
                shutil.rmtree(self.workspace, ignore_errors=True)

        self.record.duration_s = time.monotonic() - started
        self.record.finished_at = datetime.now(timezone.utc).isoformat()
        self.record.classification = classify(self._facts(blocking))
        return self.record

    def write_reports(self) -> tuple[str, str]:
        json_ref = writer.write_json(self.record, self.artifacts)
        markdown_ref = writer.write_markdown(self.record, self.artifacts)
        return json_ref, markdown_ref

    # -- stages ------------------------------------------------------------

    def _execute_matrix(
        self,
        engine: ExecutionEngine,
        analyzer: CrashAnalyzer,
        builds: dict[tuple[Version, BuildMode], BuildRecord],
    ) -> list[CasePair]:
        """Run every test case against every binary, then pair them up."""
        oracle = OracleEvaluator()
        results: dict[tuple[str, Version, BuildMode], ExecutionResult] = {}
        crashes: dict[tuple[str, Version, BuildMode], CrashInfo] = {}

        total = len(self.config.tests) * len(builds)
        done = 0
        for case in self.config.tests:
            for (version, mode), build in builds.items():
                result = engine.run_case(case, build)
                crash = analyzer.analyze(result)
                results[(case.id, version, mode)] = result
                crashes[(case.id, version, mode)] = crash
                self.record.executions.append(result)
                self.record.crashes.append(crash)
                verdict = oracle.evaluate(case, result)
                self.record.oracle_verdicts.append(verdict)
                done += 1
                log.debug(
                    "[%d/%d] %s %s/%s -> %s",
                    done,
                    total,
                    case.id,
                    version,
                    mode,
                    crash.outcome,
                )
        log.info("executed %d/%d combinations", done, total)

        verdicts = {
            (verdict.test_id, verdict.version, verdict.build_mode): verdict
            for verdict in self.record.oracle_verdicts
        }

        pairs: list[CasePair] = []
        for case in self.config.tests:
            for mode in self.config.modes:
                base_key = (case.id, "base", mode)
                patched_key = (case.id, "patched", mode)
                if base_key not in results or patched_key not in results:
                    continue
                pairs.append(
                    CasePair(
                        case=case,
                        build_mode=mode,
                        base_result=results[base_key],
                        patched_result=results[patched_key],
                        base_crash=crashes[base_key],
                        patched_crash=crashes[patched_key],
                        base_oracle=verdicts[base_key],
                        patched_oracle=verdicts[patched_key],
                    )
                )
        return pairs

    def _derive_findings(
        self, pairs: list[CasePair], patch_analyzer: PatchAnalyzer
    ) -> None:
        """Compare each pair and correlate every security finding."""
        tester = DifferentialTester()
        findings: list[Finding] = []

        for pair in pairs:
            for finding in tester.compare(pair):
                if finding.axis == "security":
                    # Correlate the side that actually faulted.  For a fault
                    # that survived or appeared, that is the patched build;
                    # for one the patch removed, the question is which hunk
                    # removed it, so the base observation is the evidence.
                    crash = _faulting_crash(finding)
                    if crash is not None:
                        correlation = patch_analyzer.correlate(
                            crash,
                            finding_id=finding.id,
                            base_behavior=finding.base_behavior,
                            patched_behavior=finding.patched_behavior,
                        )
                        self.record.correlations.append(correlation)
                        finding = finding.with_correlation(correlation)
                findings.append(finding)

        self.record.findings = findings
        log.info(
            "findings: %d security, %d functional, %d completeness",
            len([f for f in findings if f.axis == "security"]),
            len([f for f in findings if f.axis == "functional"]),
            len([f for f in findings if f.axis == "completeness"]),
        )

    def _observe_build_modes(self, pairs: list[CasePair]) -> None:
        """Record where the sanitized build saw something release did not."""
        by_test: dict[tuple[str, str], dict[str, CrashInfo]] = {}
        for pair in pairs:
            for version, crash in (
                ("base", pair.base_crash),
                ("patched", pair.patched_crash),
            ):
                by_test.setdefault((pair.case.id, version), {})[pair.build_mode] = crash

        for (test_id, version), modes in by_test.items():
            release = modes.get("release")
            sanitized = modes.get("sanitized")
            if release is None or sanitized is None:
                continue
            only_sanitizer = (
                sanitized.outcome == "security_event"
                and release.outcome not in ("security_event", "crash_unclassified")
            )
            detail = ""
            if only_sanitizer:
                detail = (
                    f"the release build reported {release.outcome} while the "
                    f"sanitized build reported {sanitized.error_type} at "
                    f"{sanitized.location or 'an unknown location'}"
                )
            self.record.build_mode_observations.append(
                BuildModeObservation(
                    test_id=test_id,
                    version=version,
                    release_outcome=_outcome_label(release),
                    sanitized_outcome=_outcome_label(sanitized),
                    revealed_only_by_sanitizer=only_sanitizer,
                    detail=detail,
                )
            )

    def _reproduce_and_minimize(
        self,
        engine: ExecutionEngine,
        analyzer: CrashAnalyzer,
        builds: dict[tuple[Version, BuildMode], BuildRecord],
        pairs: list[CasePair],
    ) -> None:
        """Minimize, bundle and turn confirmed faults into regression tests.

        One fault location is handled once.  Several inputs usually reach the
        same defect, and producing a bundle per input would multiply sandbox
        runs without adding evidence.
        """
        reproducer = ReproducerManager(self.config, engine, analyzer, self.artifacts)
        minimizer = Minimizer(self.config.minimization)
        generator = RegressionGenerator(self.artifacts)
        seen_locations: set[str] = set()

        for pair in pairs:
            crash = pair.base_crash
            if crash.outcome != "security_event":
                continue
            # Prefer the build mode that produced a symbolised signature.
            if crash.location_signature in seen_locations:
                continue
            seen_locations.add(crash.location_signature)

            build = builds[("base", pair.build_mode)]
            finding_id = f"sec/{pair.case.id}/{pair.build_mode}"
            original = pair.case.read_input()

            minimized = original
            minimization = None
            if self.config.minimization.enabled:
                result = minimizer.minimize(
                    original,
                    self._predicate(engine, analyzer, pair.case, build, crash),
                    finding_id=finding_id,
                    predicate_description=(
                        f"the execution still reports crash signature "
                        f"{crash.signature[:16]}… ({crash.error_type} at "
                        f"{crash.location or 'an unknown location'})"
                    ),
                )
                result_dict = result.to_dict()
                self.artifacts.write_json(
                    f"minimized/{_slug(finding_id)}/trace.json",
                    [attempt.to_dict() for attempt in result.attempts],
                )
                self.artifacts.write_bytes(
                    f"minimized/{_slug(finding_id)}/minimized.bin", result.minimized
                )
                self.record.minimizations.append(result)
                minimized = result.minimized
                minimization = result_dict

            reproduction = reproducer.create(
                finding_id=finding_id,
                case=pair.case,
                build=build,
                crash=crash,
                original_input=original,
                minimized_input=minimized if minimized != original else None,
                minimization=minimization,
            )
            self.record.reproductions.append(reproduction)

            generated = generator.generate(
                finding_id=finding_id,
                case=pair.case,
                base_crash=crash,
                minimized_input=minimized,
                build_mode=pair.build_mode,
                reproducible=reproduction.is_stable,
            )
            if generated is not None:
                self.record.regression_tests.append(generated)

        if self.record.regression_tests:
            generator.write_suite()

    def _predicate(
        self,
        engine: ExecutionEngine,
        analyzer: CrashAnalyzer,
        case: TestCase,
        build: BuildRecord,
        expected: CrashInfo,
    ):
        """Predicate for ddmin: same fault, in the same place, same binary."""

        def still_faults(candidate: bytes) -> bool:
            result = engine.run_case(case, build, input_data=candidate, persist=False)
            crash = analyzer.analyze(result)
            return crash.signature == expected.signature

        return still_faults

    def _analyze_hardening(
        self, builds: dict[tuple[Version, BuildMode], BuildRecord]
    ) -> None:
        base = builds.get(("base", "release"))
        patched = builds.get(("patched", "release"))
        if base is None or patched is None:
            self.record.notes.append(
                "hardening analysis skipped: both release builds are required"
            )
            return
        analyzer = HardeningAnalyzer()
        self.record.hardening = analyzer.compare(base.binary(), patched.binary())
        for warning in self.record.hardening.warnings:
            log.warning("hardening: %s", warning)

    # -- classification input ---------------------------------------------

    def _facts(self, blocking: list[str]) -> RunFacts:
        expected = len(self.config.tests) * 2 * len(self.config.modes)
        base_fault = any(
            crash.version == "base" and crash.outcome == "security_event"
            for crash in self.record.crashes
        )
        unstable = [
            reproduction.finding_id
            for reproduction in self.record.reproductions
            if not reproduction.is_stable
        ]
        correlated = {correlation.finding_id for correlation in self.record.correlations}
        uncorrelated = [
            finding.id
            for finding in self.record.findings
            if finding.axis == "security" and finding.id not in correlated
        ]
        oracle_tests = sum(1 for case in self.config.tests if case.oracle is not None)

        return RunFacts(
            findings=self.record.findings,
            blocking_errors=blocking,
            expected_executions=expected,
            completed_executions=len(self.record.executions),
            base_fault_reproduced=base_fault,
            unstable_finding_ids=unstable,
            uncorrelated_finding_ids=uncorrelated,
            hardening_analyzed=self.record.hardening is not None,
            oracle_applicable_tests=oracle_tests,
            sandbox_backend=self.record.sandbox.get("backend", "none"),
            sandbox_isolated=bool(self.record.sandbox.get("isolated", False)),
        )


def _faulting_crash(finding: Finding) -> CrashInfo | None:
    """The observation that carries the stack trace worth correlating."""
    faults = ("security_event", "crash_unclassified")
    if finding.patched_crash is not None and finding.patched_crash.outcome in faults:
        return finding.patched_crash
    if finding.base_crash is not None and finding.base_crash.outcome in faults:
        return finding.base_crash
    return finding.patched_crash or finding.base_crash


def _outcome_label(crash: CrashInfo) -> str:
    if crash.outcome == "clean":
        return f"clean (exit {crash.exit_code})"
    if crash.outcome in ("security_event", "crash_unclassified"):
        return crash.error_type
    return crash.outcome


def _slug(finding_id: str) -> str:
    return finding_id.replace("/", "__")
