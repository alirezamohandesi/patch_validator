"""Build Manager — module 3 of the architecture.

Produces one binary per (version, build mode) pair from configuration-supplied
commands, and records exactly how each one was made.

A build failure is a configuration problem, not a finding: it propagates as
:class:`BuildError` and ends the run with exit code 30 (R-BUILD-03).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from ..artifacts import ArtifactStore
from ..config import BuildMode, ValidationConfig, Version
from ..errors import BuildError
from ..util.hashing import sha256_file
from ..util.templating import FLAG_PLACEHOLDERS, render, render_argv
from ..vcs import CommitInfo, GitRepo
from .models import BuildRecord

log = logging.getLogger(__name__)

_BUILD_TIMEOUT = 1800
_ELF_MAGIC = b"\x7fELF"


class BuildManager:
    """Materialises source trees and builds them."""

    def __init__(
        self,
        config: ValidationConfig,
        repo: GitRepo,
        workspace: Path,
        artifacts: ArtifactStore,
    ) -> None:
        self.config = config
        self.repo = repo
        self.workspace = workspace
        self.artifacts = artifacts
        self._worktrees: dict[Version, Path] = {}
        self._commits: dict[Version, CommitInfo] = {}
        self._compiler_versions: dict[str, str] = {}

    # -- source preparation ------------------------------------------------

    def prepare_sources(self) -> dict[Version, Path]:
        """Check both revisions out into side-by-side worktrees."""
        for version in ("base", "patched"):
            revision = self.config.target.revision(version)  # type: ignore[arg-type]
            info = self.repo.describe(revision)
            destination = self.workspace / "src" / version
            self.repo.add_worktree(revision, destination)
            self._worktrees[version] = destination  # type: ignore[index]
            self._commits[version] = info  # type: ignore[index]
            log.info(
                "%-7s %s (%s) %s",
                version,
                revision,
                info.commit[:12],
                info.subject[:60],
            )
        if self._commits["base"].commit == self._commits["patched"].commit:
            raise BuildError(
                "base and patched revisions resolve to the same commit "
                f"({self._commits['base'].commit[:12]}): there is no patch to validate",
                remedy="check target.base_revision and target.patched_revision",
            )
        return dict(self._worktrees)

    def commit_info(self, version: Version) -> CommitInfo:
        if version not in self._commits:
            raise BuildError(f"sources for '{version}' have not been prepared")
        return self._commits[version]

    def source_path(self, version: Version) -> Path:
        """Directory the build commands run against."""
        root = self._worktrees.get(version)
        if root is None:
            raise BuildError(f"sources for '{version}' have not been prepared")
        return (root / self.config.target.source_subdir).resolve()

    def cleanup(self) -> None:
        """Remove the worktrees created by :meth:`prepare_sources`."""
        for version, path in list(self._worktrees.items()):
            self.repo.remove_worktree(path)
            self._worktrees.pop(version, None)

    # -- building ----------------------------------------------------------

    def build_all(self) -> dict[tuple[Version, BuildMode], BuildRecord]:
        """Build every (version, mode) combination the config asks for."""
        records: dict[tuple[Version, BuildMode], BuildRecord] = {}
        for version in ("base", "patched"):
            for mode in self.config.modes:
                record = self.build(version, mode)  # type: ignore[arg-type]
                records[record.key] = record
        return records

    def build(self, version: Version, mode: BuildMode) -> BuildRecord:
        spec = self.config.build(mode)
        source = self.source_path(version)
        build_dir = self.workspace / "build" / f"{version}.{mode}"
        build_dir.mkdir(parents=True, exist_ok=True)

        values = {
            "source": str(source),
            "build_dir": str(build_dir),
            "compiler": spec.compiler,
            "cflags": spec.cflags,
            "ldflags": spec.ldflags,
            "jobs": str(os.cpu_count() or 1),
            "base_dir": str(self.config.base_dir),
        }

        commands = tuple(
            tuple(
                render_argv(
                    command,
                    values,
                    context=f"build '{mode}'",
                    splittable=FLAG_PLACEHOLDERS,
                )
            )
            for command in spec.commands
        )

        env = {**os.environ, **spec.env}
        log_lines: list[str] = [
            f"# target        {self.config.target.name}",
            f"# version       {version}",
            f"# build mode    {mode}",
            f"# source        {source}",
            f"# commit        {self.commit_info(version).commit}",
            f"# compiler      {spec.compiler}",
            f"# cflags        {spec.cflags}",
            f"# ldflags       {spec.ldflags}",
            "",
        ]

        started_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        failure = ""

        for command in commands:
            log_lines.append(f"$ {' '.join(command)}")
            try:
                completed = subprocess.run(  # noqa: S603 - argv list, no shell
                    list(command),
                    cwd=str(build_dir),
                    env=env,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=_BUILD_TIMEOUT,
                    check=False,
                )
            except FileNotFoundError as exc:
                failure = f"command not found: {command[0]}"
                log_lines.append(f"!! {exc}")
                break
            except subprocess.TimeoutExpired:
                failure = f"command timed out after {_BUILD_TIMEOUT}s: {command[0]}"
                log_lines.append(f"!! {failure}")
                break

            log_lines.append(completed.stdout)
            if completed.stderr:
                log_lines.append(completed.stderr)
            if completed.returncode != 0:
                failure = (
                    f"'{' '.join(command)}' failed with exit code "
                    f"{completed.returncode}"
                )
                log_lines.append(f"!! {failure}")
                break

        duration = time.monotonic() - started
        binary_path: Path | None = None

        if not failure:
            binary_path = Path(render(spec.binary_path, values))
            if not binary_path.is_file():
                failure = f"build produced no binary at {binary_path}"
            elif binary_path.read_bytes()[:4] != _ELF_MAGIC:
                # The whole pipeline is built around executing a real ELF; a
                # script or a wrapper here would silently invalidate the
                # hardening analysis later on.
                failure = f"{binary_path} is not an ELF executable"

        log_ref = self.artifacts.write_text(
            f"builds/{version}.{mode}/build.log", "\n".join(log_lines)
        )

        record = BuildRecord(
            version=version,
            mode=mode,
            status="failed" if failure else "success",
            compiler=spec.compiler,
            compiler_version=self._compiler_version(spec.compiler),
            cflags=spec.cflags,
            ldflags=spec.ldflags,
            commands=commands,
            source_revision=self.config.target.revision(version),
            source_commit=self.commit_info(version).commit,
            source_path=str(source),
            build_dir=str(build_dir),
            started_at=started_at,
            duration_s=duration,
            binary_path=str(binary_path) if binary_path and not failure else None,
            binary_sha256=sha256_file(binary_path) if binary_path and not failure else None,
            binary_size=binary_path.stat().st_size if binary_path and not failure else None,
            log_ref=log_ref,
            failure_reason=failure,
            environment=dict(spec.env),
        )

        self.artifacts.write_json(f"builds/{version}.{mode}/meta.json", record.to_dict())

        if failure:
            raise BuildError(
                f"build of '{version}' in '{mode}' mode failed: {failure}",
                remedy=f"see {log_ref}",
                log_ref=log_ref,
            )

        log.info(
            "built %-7s %-9s %s (%s, %.1fs)",
            version,
            mode,
            binary_path.name if binary_path else "?",
            (record.binary_sha256 or "")[:12],
            duration,
        )
        return record

    def _compiler_version(self, compiler: str) -> str:
        """First line of ``<compiler> --version``, cached per compiler."""
        if compiler in self._compiler_versions:
            return self._compiler_versions[compiler]

        resolved = shutil.which(compiler)
        version = "unknown"
        if resolved is not None:
            try:
                completed = subprocess.run(  # noqa: S603 - argv list, no shell
                    [resolved, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                first = completed.stdout.splitlines()
                if first:
                    version = first[0].strip()
            except (OSError, subprocess.TimeoutExpired):  # pragma: no cover
                version = "unknown"

        self._compiler_versions[compiler] = version
        return version
