"""Report Generator — module 15 of the architecture.

Renders the machine-readable report and the developer summary from the same
run record, and validates the JSON against the published schema before
writing it.  A report that does not satisfy its own schema is a bug in the
tool, not something to hand to a pipeline.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema

from ..artifacts import ArtifactStore
from ..classify import exit_codes
from ..errors import ReportError
from .model import RunRecord

log = logging.getLogger(__name__)


def load_schema() -> dict[str, Any]:
    text = resources.files("patch_validator.report").joinpath("schema.json").read_text()
    return json.loads(text)


def validate(payload: dict[str, Any]) -> None:
    """Check a report against the published schema."""
    try:
        jsonschema.validate(payload, load_schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ReportError(
            f"the generated report violates its own schema at '{location}': "
            f"{exc.message}"
        ) from exc


def write_json(record: RunRecord, artifacts: ArtifactStore) -> str:
    payload = record.to_dict()
    validate(payload)
    return artifacts.write_json("report.json", payload)


def write_markdown(record: RunRecord, artifacts: ArtifactStore) -> str:
    return artifacts.write_text("report.md", render_markdown(record))


def render_markdown(record: RunRecord) -> str:
    """Developer-facing summary of a run."""
    classification = record.classification
    lines: list[str] = []
    add = lines.append

    add(f"# Patch validation report — {record.config.target.name}")
    add("")
    add(f"Run `{record.run_id}` · config `{record.config.config_path.name}`")
    add("")

    # -- verdict
    if classification is not None:
        add("## Verdict")
        add("")
        add(f"**{classification.final_classification}** (exit code "
            f"{classification.exit_code})")
        add("")
        add(f"> {exit_codes.EXIT_DESCRIPTIONS.get(classification.exit_code, '')}")
        add("")
        add("| axis | status |")
        add("|---|---|")
        add(f"| security | `{classification.security_status}` |")
        add(f"| functional | `{classification.functional_status}` |")
        add(f"| analysis completeness | `{classification.completeness_status}` |")
        add("")
        if classification.rationale:
            add("### Why")
            add("")
            for reason in classification.rationale:
                add(f"- {reason}")
            add("")

    # -- what was compared
    add("## What was compared")
    add("")
    add("| | revision | commit | subject |")
    add("|---|---|---|---|")
    for version in ("base", "patched"):
        info = record.commits.get(version)
        if info is None:
            continue
        add(
            f"| {version} | `{info.revision}` | `{info.commit[:12]}` | "
            f"{_escape(info.subject)} |"
        )
    add("")
    if record.patch_summary:
        files = record.patch_summary.get("file_count", "?")
        hunks = record.patch_summary.get("hunk_count", "?")
        add(f"The patch touches {files} file(s) in {hunks} hunk(s).")
        changed = record.patch_summary.get("changed_functions") or {}
        for path, functions in changed.items():
            names = ", ".join(f"`{name}()`" for name in sorted(functions)) or "—"
            add(f"- `{path}`: {names}")
        add("")

    # -- builds
    add("## Builds")
    add("")
    add("| version | mode | compiler | flags | sha256 |")
    add("|---|---|---|---|---|")
    for build in record.builds:
        add(
            f"| {build.version} | {build.mode} | {_escape(build.compiler_version)} | "
            f"`{_escape(build.cflags)}` | `{(build.binary_sha256 or '')[:12]}` |"
        )
    add("")

    # -- security findings
    security = record.findings_by_axis("security")
    add("## Security findings")
    add("")
    if not security:
        add("No security-relevant difference was observed between the two builds.")
        add("")
    else:
        for finding in security:
            add(f"### `{finding.kind}` — {finding.test_id} ({finding.build_mode})")
            add("")
            add(f"{finding.summary}")
            add("")
            add(f"- confidence: `{finding.confidence}`")
            add(f"- base: {finding.base_behavior}")
            add(f"- patched: {finding.patched_behavior}")
            if finding.signature_changed:
                add("- the fault moved to a different location after the patch")
            correlation = finding.correlation
            if correlation is not None:
                add(
                    f"- correlation with the diff: `{correlation.status}` "
                    f"(confidence `{correlation.confidence}`)"
                )
                if correlation.affected_function:
                    add(
                        f"  - affected: `{correlation.affected_file}` in "
                        f"`{correlation.affected_function}()`"
                    )
                if correlation.indirect:
                    add("  - the relationship is indirect, through a caller")
                for evidence in correlation.correlation_evidence[:3]:
                    add(f"  - {evidence}")
            for note in finding.notes:
                add(f"- note: {note}")
            if finding.evidence_refs:
                refs = ", ".join(f"`{ref}`" for ref in finding.evidence_refs)
                add(f"- evidence: {refs}")
            add("")

    # -- functional findings
    functional = record.findings_by_axis("functional")
    add("## Functional findings")
    add("")
    if not functional:
        add("Every test case with an oracle behaved identically and correctly "
            "on both builds.")
        add("")
    else:
        add("| kind | test | mode | authoritative | summary |")
        add("|---|---|---|---|---|")
        for finding in functional:
            add(
                f"| `{finding.kind}` | {finding.test_id} | {finding.build_mode} | "
                f"{'yes' if finding.authoritative else 'no'} | "
                f"{_escape(finding.summary)} |"
            )
        add("")

    # -- build mode comparison
    if record.build_mode_observations:
        revealing = [
            observation
            for observation in record.build_mode_observations
            if observation.revealed_only_by_sanitizer
        ]
        add("## Release build versus sanitized build")
        add("")
        if revealing:
            add(
                f"{len(revealing)} case(s) produced a fault only under the "
                "sanitized build. The release build gave no indication of a "
                "problem for these inputs:"
            )
            add("")
            add("| test | version | release | sanitized |")
            add("|---|---|---|---|")
            for observation in revealing:
                add(
                    f"| {observation.test_id} | {observation.version} | "
                    f"{observation.release_outcome} | "
                    f"{observation.sanitized_outcome} |"
                )
        else:
            add("No case was revealed exclusively by the sanitized build.")
        add("")

    # -- reproduction and minimization
    if record.reproductions:
        add("## Reproduction")
        add("")
        add("| finding | replays | matched | stability | bundle |")
        add("|---|---|---|---|---|")
        for reproduction in record.reproductions:
            add(
                f"| `{reproduction.finding_id}` | {len(reproduction.replays)} | "
                f"{reproduction.matched_count} | `{reproduction.stability}` | "
                f"`{reproduction.bundle_ref}` |"
            )
        add("")

    if record.minimizations:
        add("## Minimization")
        add("")
        add("| finding | original | minimized | reduction | probes | stopped because |")
        add("|---|---|---|---|---|---|")
        for result in record.minimizations:
            add(
                f"| `{result.finding_id}` | {result.original_size} B | "
                f"{result.minimized_size} B | {result.reduction_percent}% | "
                f"{result.iterations} | {result.stop_reason} |"
            )
        add("")

    if record.regression_tests:
        add("## Generated regression tests")
        add("")
        for case in record.regression_tests:
            add(
                f"- `{case.id}` ({case.input_size} B) from finding "
                f"`{case.source_finding}` → `{case.case_ref}`"
            )
        add("")

    # -- hardening
    if record.hardening is not None:
        add("## Binary hardening")
        add("")
        add("| protection | base | patched | change |")
        add("|---|---|---|---|")
        for comparison in record.hardening.comparisons:
            add(
                f"| {comparison.name} | `{comparison.base}` | "
                f"`{comparison.patched}` | `{comparison.change_status}` |"
            )
        add("")
        for warning in record.hardening.warnings:
            add(f"> **Warning**: {warning}")
            add("")
        add("Limitations of this analysis:")
        add("")
        for limitation in record.hardening.limitations:
            add(f"- {limitation}")
        add("")

    # -- completeness
    if classification is not None:
        add("## Mandatory checks")
        add("")
        add("| check | result | detail |")
        add("|---|---|---|")
        for check in classification.mandatory_checks:
            mark = "pass" if check.passed else "**FAIL**"
            add(f"| {check.name} | {mark} | {_escape(check.detail)} |")
        add("")

    gaps = record.findings_by_axis("completeness")
    if gaps:
        add("## Analysis gaps")
        add("")
        for finding in gaps:
            add(f"- `{finding.kind}` {finding.test_id}: {finding.summary}")
        add("")

    add("## Environment")
    add("")
    sandbox = record.sandbox
    add(f"- sandbox backend: `{sandbox.get('backend', 'unknown')}`")
    add(f"- isolated: {'yes' if sandbox.get('isolated') else 'NO'}")
    for key in ("platform", "kernel", "python"):
        if key in record.environment:
            add(f"- {key}: {record.environment[key]}")
    image = record.environment.get("image_digest")
    if image:
        add(f"- container image: `{image}`")
    add("")

    add("---")
    add("")
    add(
        "Every claim above is backed by an artifact under this run directory. "
        "Paths in the `evidence` fields are relative to it."
    )
    add("")
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Make a value safe to drop into a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def write_patch_diff(diff_text: str, artifacts: ArtifactStore) -> str:
    return artifacts.write_text("patch.diff", diff_text)


def report_paths(artifacts: ArtifactStore) -> tuple[Path, Path]:
    return artifacts.root / "report.json", artifacts.root / "report.md"
