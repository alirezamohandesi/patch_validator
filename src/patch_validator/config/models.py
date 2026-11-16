"""Typed configuration model.

Everything that is specific to a target program lives here, loaded from YAML.
The analysis modules depend on these dataclasses and never on a particular
target, which is what allows a new program to be added with a configuration
file alone (R-SCOPE-08).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..errors import ConfigError

BuildMode = Literal["release", "sanitized"]
Version = Literal["base", "patched"]

#: The two source versions every comparison is made between.
VERSIONS: tuple[Version, ...] = ("base", "patched")


@dataclass(frozen=True)
class TargetSpec:
    """Which program, and which two revisions of it, are under test."""

    name: str
    language: str
    repo_path: Path
    source_subdir: str
    base_revision: str
    patched_revision: str
    description: str = ""

    def revision(self, version: Version) -> str:
        return self.base_revision if version == "base" else self.patched_revision


@dataclass(frozen=True)
class BuildSpec:
    """How to produce one binary for one build mode.

    ``commands`` and ``binary_path`` are templates; the available placeholders
    are ``{source}``, ``{build_dir}``, ``{compiler}``, ``{cflags}``,
    ``{ldflags}`` and ``{jobs}``.
    """

    mode: BuildMode
    compiler: str
    cflags: str
    ldflags: str
    commands: tuple[str | tuple[str, ...], ...]
    binary_path: str
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_sanitized(self) -> bool:
        return self.mode == "sanitized"


@dataclass(frozen=True)
class InputSpec:
    """How a test input reaches the target process."""

    method: Literal["stdin", "file", "argv"]
    argv: tuple[str, ...] = ()
    filename: str = "input.bin"

    def __post_init__(self) -> None:
        placeholder = {"file": "{input_file}", "argv": "{input_arg}"}.get(self.method)
        if placeholder is None:
            return
        if not any(placeholder in arg for arg in self.argv):
            raise ConfigError(
                f"input.method '{self.method}' requires {placeholder} "
                f"in input.argv, got {list(self.argv)}"
            )


@dataclass(frozen=True)
class OutputMatcher:
    """One expectation about a stream of program output."""

    match: Literal["exact", "contains", "regex", "absent", "ignore"] = "ignore"
    value: str = ""

    def describe(self) -> str:
        if self.match in ("ignore", "absent"):
            return self.match
        return f"{self.match}:{self.value!r}"


@dataclass(frozen=True)
class OracleSpec:
    """Expected behaviour of a *correct* implementation for one input.

    Derived from the target's own specification or upstream documentation,
    never from the output of the patched build (ADR-006).
    """

    source: Literal[
        "specification", "upstream_docs", "reference_test_suite", "instructor_approved"
    ]
    input_validity: Literal["valid", "boundary", "invalid"]
    exit_code: int | None = None
    stdout: OutputMatcher = field(default_factory=OutputMatcher)
    stderr: OutputMatcher = field(default_factory=OutputMatcher)
    semantics: str = ""
    instructor_approved: Literal["yes", "no", "pending"] = "pending"


@dataclass(frozen=True)
class TestCase:
    """One input, executed identically against every binary in the matrix."""

    id: str
    category: Literal["valid", "boundary", "invalid", "security"]
    input_path: Path | None = None
    input_inline: bytes | None = None
    oracle: OracleSpec | None = None
    timeout_s: float | None = None
    #: Free-form note carried into the report; never used to decide a verdict.
    note: str = ""

    def read_input(self) -> bytes:
        if self.input_inline is not None:
            return self.input_inline
        if self.input_path is None:
            raise ConfigError(f"test '{self.id}' has no input")
        try:
            return self.input_path.read_bytes()
        except OSError as exc:
            raise ConfigError(f"test '{self.id}': cannot read input: {exc}") from exc

    @staticmethod
    def decode_inline(spec: dict[str, str], test_id: str) -> bytes:
        if "text" in spec:
            return spec["text"].encode()
        if "base64" in spec:
            try:
                return base64.b64decode(spec["base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ConfigError(f"test '{test_id}': invalid base64 input: {exc}") from exc
        raise ConfigError(f"test '{test_id}': inline input needs 'text' or 'base64'")


@dataclass(frozen=True)
class Limits:
    """Resource ceilings applied to every target execution."""

    timeout_s: float = 10.0
    memory_mb: int = 1024
    cpu_s: int = 10
    max_processes: int = 64
    max_output_bytes: int = 1 << 20
    max_file_size_mb: int = 64


@dataclass(frozen=True)
class SandboxSpec:
    """Isolation policy for target executions."""

    backend: Literal["bubblewrap", "subprocess"] = "bubblewrap"
    network: bool = False
    unsafe_ack: bool = False
    extra_ro_binds: tuple[Path, ...] = ()


@dataclass(frozen=True)
class MinimizationSpec:
    enabled: bool = True
    max_iterations: int = 2000
    budget_seconds: float = 120.0


@dataclass(frozen=True)
class ReproductionSpec:
    #: The specification requires at least three replays per confirmed finding.
    replays: int = 3


@dataclass(frozen=True)
class ValidationConfig:
    """A fully resolved, ready-to-execute validation job."""

    schema_version: int
    target: TargetSpec
    builds: tuple[BuildSpec, ...]
    input: InputSpec
    limits: Limits
    sandbox: SandboxSpec
    tests: tuple[TestCase, ...]
    minimization: MinimizationSpec
    reproduction: ReproductionSpec
    base_dir: Path
    config_path: Path

    def build(self, mode: BuildMode) -> BuildSpec:
        for spec in self.builds:
            if spec.mode == mode:
                return spec
        raise ConfigError(f"no build configured for mode '{mode}'")

    @property
    def modes(self) -> tuple[BuildMode, ...]:
        return tuple(spec.mode for spec in self.builds)

    def test(self, test_id: str) -> TestCase:
        for case in self.tests:
            if case.id == test_id:
                return case
        raise ConfigError(f"no test case with id '{test_id}'")
