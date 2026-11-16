"""Reproducer Manager — module 11 of the architecture.

Packages a confirmed finding into a self-contained bundle and proves it is
reproducible by replaying it.

The specification requires at least three replays with each result recorded
separately, and requires unstable findings to be called out rather than
averaged away (SPEC 3.3).  A finding that reproduces twice out of three is
useless as a regression test, so saying so is more valuable than reporting a
success rate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..analysis.crash import CrashAnalyzer, CrashInfo
from ..artifacts import ArtifactStore
from ..build import BuildRecord
from ..config import TestCase, ValidationConfig
from ..execution import ExecutionEngine
from ..util.hashing import sha256_bytes
from ..util import environment

log = logging.getLogger(__name__)

Stability = Literal["stable", "flaky", "not_reproduced"]

#: Bundle format version, so a future reader can tell what it is looking at.
BUNDLE_VERSION = "1.0"


@dataclass(frozen=True)
class ReplayRecord:
    """One replay attempt, recorded in full."""

    index: int
    exit_code: int | None
    signal: int | None
    signal_name: str | None
    timed_out: bool
    duration_s: float
    error_type: str
    signature: str
    matched_expected: bool
    stdout_ref: str = ""
    stderr_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "signal_name": self.signal_name,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 6),
            "error_type": self.error_type,
            "crash_signature": self.signature,
            "matched_expected": self.matched_expected,
            "stdout_ref": self.stdout_ref,
            "stderr_ref": self.stderr_ref,
        }


@dataclass(frozen=True)
class Reproduction:
    finding_id: str
    stability: Stability
    expected_signature: str
    expected_error_type: str
    replays: tuple[ReplayRecord, ...]
    bundle_ref: str
    manifest_ref: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def matched_count(self) -> int:
        return sum(1 for replay in self.replays if replay.matched_expected)

    @property
    def is_stable(self) -> bool:
        return self.stability == "stable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "stability": self.stability,
            "expected_error_type": self.expected_error_type,
            "expected_signature": self.expected_signature,
            "replay_count": len(self.replays),
            "matched_count": self.matched_count,
            "replays": [replay.to_dict() for replay in self.replays],
            "bundle_ref": self.bundle_ref,
            "manifest_ref": self.manifest_ref,
            "notes": list(self.notes),
        }


class ReproducerManager:
    """Builds reproducer bundles and verifies them by replay."""

    def __init__(
        self,
        config: ValidationConfig,
        engine: ExecutionEngine,
        analyzer: CrashAnalyzer,
        artifacts: ArtifactStore,
    ) -> None:
        self.config = config
        self.engine = engine
        self.analyzer = analyzer
        self.artifacts = artifacts

    def create(
        self,
        *,
        finding_id: str,
        case: TestCase,
        build: BuildRecord,
        crash: CrashInfo,
        original_input: bytes,
        minimized_input: bytes | None = None,
        minimization: dict[str, Any] | None = None,
    ) -> Reproduction:
        """Write a bundle for ``finding_id`` and replay it to prove it works."""
        slug = _slug(finding_id)
        base = f"bundles/{slug}"
        replay_input = minimized_input if minimized_input is not None else original_input

        self.artifacts.write_bytes(f"{base}/input.bin", original_input)
        if minimized_input is not None:
            self.artifacts.write_bytes(f"{base}/minimized.bin", minimized_input)
        self.artifacts.write_text(f"{base}/crash.txt", _crash_report(crash))

        replays = self._replay_many(
            case=case,
            build=build,
            data=replay_input,
            expected=crash,
            artifact_base=f"{base}/replays",
        )
        stability = _stability(replays)

        notes: list[str] = []
        if stability == "flaky":
            notes.append(
                f"only {sum(r.matched_expected for r in replays)} of "
                f"{len(replays)} replays reproduced the recorded fault; this "
                f"finding is unstable and is not a sound basis for a "
                f"regression test"
            )
        elif stability == "not_reproduced":
            notes.append(
                "no replay reproduced the recorded fault; the original "
                "observation could not be confirmed"
            )

        manifest = self._manifest(
            finding_id=finding_id,
            case=case,
            build=build,
            crash=crash,
            original_input=original_input,
            minimized_input=minimized_input,
            minimization=minimization,
            replays=replays,
            stability=stability,
        )
        manifest_ref = self.artifacts.write_json(f"{base}/manifest.json", manifest)
        self.artifacts.write_text(
            f"{base}/REPRODUCE.md", _instructions(manifest, minimized_input is not None)
        )

        reproduction = Reproduction(
            finding_id=finding_id,
            stability=stability,
            expected_signature=crash.signature,
            expected_error_type=crash.error_type,
            replays=replays,
            bundle_ref=base,
            manifest_ref=manifest_ref,
            notes=tuple(notes),
        )
        log.info(
            "bundle %s: %s (%d/%d replays matched)",
            slug,
            stability,
            reproduction.matched_count,
            len(replays),
        )
        return reproduction

    def _replay_many(
        self,
        *,
        case: TestCase,
        build: BuildRecord,
        data: bytes,
        expected: CrashInfo,
        artifact_base: str,
    ) -> tuple[ReplayRecord, ...]:
        records: list[ReplayRecord] = []
        for index in range(self.config.reproduction.replays):
            result = self.engine.run_case(
                case,
                build,
                input_data=data,
                artifact_prefix=f"{artifact_base}/{index}",
            )
            crash = self.analyzer.analyze(result)
            records.append(
                ReplayRecord(
                    index=index,
                    exit_code=result.exit_code,
                    signal=result.signal,
                    signal_name=result.signal_name,
                    timed_out=result.timed_out,
                    duration_s=result.duration_s,
                    error_type=crash.error_type,
                    signature=crash.signature,
                    matched_expected=crash.signature == expected.signature,
                    stdout_ref=result.stdout_ref,
                    stderr_ref=result.stderr_ref,
                )
            )
        return tuple(records)

    def _manifest(
        self,
        *,
        finding_id: str,
        case: TestCase,
        build: BuildRecord,
        crash: CrashInfo,
        original_input: bytes,
        minimized_input: bytes | None,
        minimization: dict[str, Any] | None,
        replays: tuple[ReplayRecord, ...],
        stability: Stability,
    ) -> dict[str, Any]:
        sample = replays[0] if replays else None
        del sample
        limits = self.config.limits
        return {
            "bundle_version": BUNDLE_VERSION,
            "finding_id": finding_id,
            "target": {
                "name": self.config.target.name,
                "repo_path": str(self.config.target.repo_path),
                "source_subdir": self.config.target.source_subdir,
            },
            "test_case": {
                "id": case.id,
                "category": case.category,
                "note": case.note,
            },
            "version": build.version,
            "commit": build.source_commit,
            "revision": build.source_revision,
            "build": {
                "mode": build.mode,
                "compiler": build.compiler,
                "compiler_version": build.compiler_version,
                "cflags": build.cflags,
                "ldflags": build.ldflags,
                "commands": [list(command) for command in build.commands],
                "binary_path": build.binary_path,
                "binary_sha256": build.binary_sha256,
            },
            "input": {
                "method": self.config.input.method,
                "argv_template": list(self.config.input.argv),
                "filename": self.config.input.filename,
                "original_sha256": sha256_bytes(original_input),
                "original_size": len(original_input),
                "minimized_sha256": (
                    sha256_bytes(minimized_input) if minimized_input else None
                ),
                "minimized_size": (
                    len(minimized_input) if minimized_input is not None else None
                ),
            },
            "minimization": minimization,
            "execution": {
                "command": list(crash.extra.get("argv", "").split(" "))
                if crash.extra.get("argv")
                else None,
                "environment": dict(build.environment),
                "timeout_s": case.timeout_s or limits.timeout_s,
                "resource_limits": {
                    "memory_mb": limits.memory_mb,
                    "cpu_s": limits.cpu_s,
                    "max_processes": limits.max_processes,
                    "max_output_bytes": limits.max_output_bytes,
                },
            },
            "sandbox": {
                "backend": self.config.sandbox.backend,
                "network": self.config.sandbox.network,
            },
            "crash": crash.to_dict(),
            "replays": [replay.to_dict() for replay in replays],
            "stability": stability,
            "environment": environment.capture(),
        }


def load_manifest(bundle: Path) -> dict[str, Any]:
    """Read a bundle manifest from disk."""
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.json in {bundle}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _stability(replays: tuple[ReplayRecord, ...]) -> Stability:
    if not replays:
        return "not_reproduced"
    matched = sum(1 for replay in replays if replay.matched_expected)
    if matched == len(replays):
        return "stable"
    if matched == 0:
        return "not_reproduced"
    return "flaky"


def _crash_report(crash: CrashInfo) -> str:
    lines = [
        f"finding       {crash.test_id} ({crash.version}, {crash.build_mode})",
        f"error type    {crash.error_type}",
        f"detected by   {crash.detection_mechanism}",
        f"confidence    {crash.confidence}",
        f"location      {crash.location or 'unknown'}",
        f"signature     {crash.signature}",
        f"location sig  {crash.location_signature}",
        f"message       {crash.message}",
        "",
        "stack trace:",
    ]
    lines.extend(f"  {frame.raw or frame.describe()}" for frame in crash.frames)
    if crash.notes:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"  - {note}" for note in crash.notes)
    return "\n".join(lines) + "\n"


def _instructions(manifest: dict[str, Any], has_minimized: bool) -> str:
    build = manifest["build"]
    commands = "\n".join("    " + " ".join(command) for command in build["commands"])
    input_name = "minimized.bin" if has_minimized else "input.bin"
    return f"""# Reproducing {manifest['finding_id']}

Everything needed to observe this fault again is in this directory.

## What was observed

    {manifest['crash']['error_type']} detected by {manifest['crash']['detection_mechanism']}
    at {manifest['crash']['location'] or 'an unknown location'}

Replayed {len(manifest['replays'])} times during the run; result: {manifest['stability']}.

## Exact version

    repository   {manifest['target']['repo_path']}
    revision     {manifest['revision']}
    commit       {manifest['commit']}
    version      {manifest['version']}

## Exact binary

    path         {build['binary_path']}
    sha256       {build['binary_sha256']}
    compiler     {build['compiler_version']}
    cflags       {build['cflags']}
    ldflags      {build['ldflags']}

If the binary is gone, rebuild it from the commit above with:

{commands}

## Replay

    patch-validator reproduce <path to this directory>

The command rebuilds nothing. It checks the binary against the recorded
SHA256, feeds it `{input_name}` through the recorded input method
({manifest['input']['method']}) under the same sandbox and resource limits,
and reports whether the same crash signature appears.

## Input

    original     input.bin ({manifest['input']['original_size']} bytes, sha256 {manifest['input']['original_sha256']})
""" + (
        f"    minimized    minimized.bin ({manifest['input']['minimized_size']} bytes, "
        f"sha256 {manifest['input']['minimized_sha256']})\n"
        if has_minimized
        else ""
    )


def _slug(finding_id: str) -> str:
    return finding_id.replace("/", "__")
