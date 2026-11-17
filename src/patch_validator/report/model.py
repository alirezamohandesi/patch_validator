"""The run record: one object holding everything a run observed.

Both the JSON report and the human-readable summary are rendered from this
single object, which is how they are kept from contradicting each other
(R-CICD-04).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import REPORT_SCHEMA_VERSION, __version__
from ..analysis.crash import CrashInfo
from ..analysis.findings import Finding
from ..analysis.hardening import HardeningReport
from ..analysis.oracle import OracleVerdict
from ..analysis.patch import Correlation
from ..build import BuildRecord
from ..classify import Classification
from ..config import ValidationConfig
from ..execution import ExecutionResult
from ..minimize import MinimizationResult
from ..regression.generator import RegressionCase
from ..reproducer import Reproduction
from ..vcs import CommitInfo


@dataclass
class BuildModeObservation:
    """What each build mode revealed for one test case.

    Recorded explicitly because the specification asks for it: the value of
    running both builds is precisely that they disagree sometimes, and that
    disagreement has to be visible rather than averaged away (R-DYN-09).
    """

    test_id: str
    version: str
    release_outcome: str
    sanitized_outcome: str
    revealed_only_by_sanitizer: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "version": self.version,
            "release_outcome": self.release_outcome,
            "sanitized_outcome": self.sanitized_outcome,
            "revealed_only_by_sanitizer": self.revealed_only_by_sanitizer,
            "detail": self.detail,
        }


@dataclass
class RunRecord:
    """Everything one validation run produced."""

    run_id: str
    started_at: str
    config: ValidationConfig
    command: list[str] = field(default_factory=list)
    finished_at: str = ""
    duration_s: float = 0.0

    environment: dict[str, Any] = field(default_factory=dict)
    sandbox: dict[str, Any] = field(default_factory=dict)
    commits: dict[str, CommitInfo] = field(default_factory=dict)
    patch_summary: dict[str, Any] = field(default_factory=dict)

    builds: list[BuildRecord] = field(default_factory=list)
    executions: list[ExecutionResult] = field(default_factory=list)
    crashes: list[CrashInfo] = field(default_factory=list)
    oracle_verdicts: list[OracleVerdict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    correlations: list[Correlation] = field(default_factory=list)
    reproductions: list[Reproduction] = field(default_factory=list)
    minimizations: list[MinimizationResult] = field(default_factory=list)
    regression_tests: list[RegressionCase] = field(default_factory=list)
    hardening: HardeningReport | None = None
    build_mode_observations: list[BuildModeObservation] = field(default_factory=list)
    classification: Classification | None = None
    notes: list[str] = field(default_factory=list)

    # -- convenience views -------------------------------------------------

    def findings_by_axis(self, axis: str) -> list[Finding]:
        return [finding for finding in self.findings if finding.axis == axis]

    @property
    def exit_code(self) -> int:
        return self.classification.exit_code if self.classification else 40

    def to_dict(self) -> dict[str, Any]:
        target = self.config.target
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool": {"name": "patch-validator", "version": __version__},
            "run": {
                "id": self.run_id,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_s": round(self.duration_s, 3),
                "config_path": str(self.config.config_path),
                "command": list(self.command),
            },
            "environment": dict(self.environment),
            "sandbox": dict(self.sandbox),
            "target": {
                "name": target.name,
                "description": target.description,
                "language": target.language,
                "repo_path": str(target.repo_path),
                "source_subdir": target.source_subdir,
            },
            "revisions": {
                version: info.to_dict() for version, info in self.commits.items()
            },
            "patch": dict(self.patch_summary),
            "builds": [record.to_dict() for record in self.builds],
            "test_configuration": {
                "input": {
                    "method": self.config.input.method,
                    "argv": list(self.config.input.argv),
                    "filename": self.config.input.filename,
                },
                "limits": {
                    "timeout_s": self.config.limits.timeout_s,
                    "memory_mb": self.config.limits.memory_mb,
                    "cpu_s": self.config.limits.cpu_s,
                    "max_processes": self.config.limits.max_processes,
                    "max_output_bytes": self.config.limits.max_output_bytes,
                },
                "build_modes": list(self.config.modes),
                "tests": [
                    {
                        "id": case.id,
                        "category": case.category,
                        "has_oracle": case.oracle is not None,
                        "oracle_source": case.oracle.source if case.oracle else None,
                        "instructor_approved": (
                            case.oracle.instructor_approved if case.oracle else None
                        ),
                        "note": case.note,
                    }
                    for case in self.config.tests
                ],
            },
            "executions": [result.to_dict() for result in self.executions],
            "crash_evidence": [crash.to_dict() for crash in self.crashes],
            "oracle_verdicts": [verdict.to_dict() for verdict in self.oracle_verdicts],
            "findings": {
                "security": [
                    finding.to_dict() for finding in self.findings_by_axis("security")
                ],
                "functional": [
                    finding.to_dict() for finding in self.findings_by_axis("functional")
                ],
                "completeness": [
                    finding.to_dict()
                    for finding in self.findings_by_axis("completeness")
                ],
            },
            "patch_correlations": [
                correlation.to_dict() for correlation in self.correlations
            ],
            "reproductions": [
                reproduction.to_dict() for reproduction in self.reproductions
            ],
            "minimizations": [result.to_dict() for result in self.minimizations],
            "regression_tests": [case.to_dict() for case in self.regression_tests],
            "hardening": self.hardening.to_dict() if self.hardening else None,
            "build_mode_comparison": [
                observation.to_dict() for observation in self.build_mode_observations
            ],
            "classification": (
                self.classification.to_dict() if self.classification else None
            ),
            "exit_code": self.exit_code,
            "notes": list(self.notes),
        }
