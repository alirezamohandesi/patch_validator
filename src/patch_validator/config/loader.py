"""Load, validate and resolve a target configuration file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .. import CONFIG_SCHEMA_VERSION
from ..errors import ConfigError
from ..util.templating import unknown_placeholders
from .models import (
    BuildSpec,
    InputSpec,
    Limits,
    MinimizationSpec,
    OracleSpec,
    OutputMatcher,
    ReproductionSpec,
    SandboxSpec,
    TargetSpec,
    TestCase,
    ValidationConfig,
)
from .schema import CONFIG_SCHEMA

log = logging.getLogger(__name__)

BUILD_PLACEHOLDERS = ("source", "build_dir", "compiler", "cflags", "ldflags", "jobs")
INPUT_PLACEHOLDERS = ("input_file", "input_arg", "binary", "workdir")


def load_config(path: Path) -> ValidationConfig:
    """Parse ``path`` and return a fully resolved configuration.

    Raises :class:`ConfigError` for anything wrong with the file, including
    schema violations, unknown placeholders and missing input files.
    """
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ConfigError(
            f"configuration file not found: {path}",
            remedy="pass an existing YAML file with --config",
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    try:
        jsonschema.validate(raw, CONFIG_SCHEMA)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ConfigError(
            f"{path}: schema violation at '{location}': {exc.message}",
            remedy="see docs/CONFIGURATION.md for the accepted structure",
        ) from exc

    if raw["schema_version"] != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"{path}: schema_version {raw['schema_version']} is not supported "
            f"(this tool speaks version {CONFIG_SCHEMA_VERSION})"
        )

    base_dir = (path.parent / raw.get("base_dir", ".")).resolve()

    config = ValidationConfig(
        schema_version=raw["schema_version"],
        target=_target(raw["target"], base_dir),
        builds=_builds(raw["builds"]),
        input=_input(raw["input"]),
        limits=_limits(raw.get("limits", {})),
        sandbox=_sandbox(raw.get("sandbox", {}), base_dir),
        tests=_tests(raw["tests"], base_dir),
        minimization=MinimizationSpec(**raw.get("minimization", {})),
        reproduction=ReproductionSpec(**raw.get("reproduction", {})),
        base_dir=base_dir,
        config_path=path,
    )
    _check_consistency(config)
    log.debug(
        "loaded configuration for target '%s': %d tests, modes %s",
        config.target.name,
        len(config.tests),
        ", ".join(config.modes),
    )
    return config


def _target(raw: dict[str, Any], base_dir: Path) -> TargetSpec:
    repo_path = (base_dir / raw["repo_path"]).resolve()
    return TargetSpec(
        name=raw["name"],
        language=raw.get("language", "c"),
        repo_path=repo_path,
        source_subdir=raw.get("source_subdir", "."),
        base_revision=raw["base_revision"],
        patched_revision=raw["patched_revision"],
        description=raw.get("description", ""),
    )


def _builds(raw: list[dict[str, Any]]) -> tuple[BuildSpec, ...]:
    specs: list[BuildSpec] = []
    seen: set[str] = set()
    for entry in raw:
        mode = entry["mode"]
        if mode in seen:
            raise ConfigError(f"duplicate build mode '{mode}'")
        seen.add(mode)

        commands = tuple(
            tuple(command) if isinstance(command, list) else command
            for command in entry["commands"]
        )
        for command in commands:
            parts = [command] if isinstance(command, str) else list(command)
            for part in parts:
                unknown = unknown_placeholders(part, BUILD_PLACEHOLDERS)
                if unknown:
                    raise ConfigError(
                        f"build '{mode}': unknown placeholder(s) "
                        f"{', '.join('{' + name + '}' for name in unknown)} in {part!r}",
                        remedy=f"available: {', '.join('{' + p + '}' for p in BUILD_PLACEHOLDERS)}",
                    )

        unknown = unknown_placeholders(entry["binary_path"], BUILD_PLACEHOLDERS)
        if unknown:
            raise ConfigError(
                f"build '{mode}': unknown placeholder(s) in binary_path: "
                f"{', '.join(unknown)}"
            )

        specs.append(
            BuildSpec(
                mode=mode,
                compiler=entry.get("compiler", "cc"),
                cflags=entry.get("cflags", ""),
                ldflags=entry.get("ldflags", ""),
                commands=commands,
                binary_path=entry["binary_path"],
                env=dict(entry.get("env", {})),
            )
        )
    return tuple(specs)


def _input(raw: dict[str, Any]) -> InputSpec:
    argv = tuple(raw.get("argv", ()))
    for arg in argv:
        unknown = unknown_placeholders(arg, INPUT_PLACEHOLDERS)
        if unknown:
            raise ConfigError(
                f"input.argv: unknown placeholder(s) {', '.join(unknown)} in {arg!r}",
                remedy=f"available: {', '.join('{' + p + '}' for p in INPUT_PLACEHOLDERS)}",
            )
    return InputSpec(
        method=raw["method"],
        argv=argv,
        filename=raw.get("filename", "input.bin"),
    )


def _limits(raw: dict[str, Any]) -> Limits:
    return Limits(**raw)


def _sandbox(raw: dict[str, Any], base_dir: Path) -> SandboxSpec:
    binds = tuple((base_dir / entry).resolve() for entry in raw.get("extra_ro_binds", ()))
    return SandboxSpec(
        backend=raw.get("backend", "bubblewrap"),
        network=raw.get("network", False),
        unsafe_ack=raw.get("unsafe_ack", False),
        extra_ro_binds=binds,
    )


def _matcher(raw: dict[str, Any] | None) -> OutputMatcher:
    if raw is None:
        return OutputMatcher()
    return OutputMatcher(match=raw["match"], value=raw.get("value", ""))


def _oracle(raw: dict[str, Any] | None) -> OracleSpec | None:
    if raw is None:
        return None
    return OracleSpec(
        source=raw["source"],
        input_validity=raw["input_validity"],
        exit_code=raw.get("exit_code"),
        stdout=_matcher(raw.get("stdout")),
        stderr=_matcher(raw.get("stderr")),
        semantics=raw.get("semantics", ""),
        instructor_approved=raw.get("instructor_approved", "pending"),
    )


def _tests(raw: list[dict[str, Any]], base_dir: Path) -> tuple[TestCase, ...]:
    cases: list[TestCase] = []
    seen: set[str] = set()
    for entry in raw:
        test_id = entry["id"]
        if test_id in seen:
            raise ConfigError(f"duplicate test id '{test_id}'")
        seen.add(test_id)

        spec = entry["input"]
        input_path: Path | None = None
        input_inline: bytes | None = None
        if "path" in spec:
            input_path = (base_dir / spec["path"]).resolve()
            if not input_path.is_file():
                raise ConfigError(
                    f"test '{test_id}': input file not found: {input_path}",
                    remedy="generate the corpus first, see the target's README",
                )
        else:
            input_inline = TestCase.decode_inline(spec, test_id)

        cases.append(
            TestCase(
                id=test_id,
                category=entry["category"],
                input_path=input_path,
                input_inline=input_inline,
                oracle=_oracle(entry.get("oracle")),
                timeout_s=entry.get("timeout_s"),
                note=entry.get("note", ""),
            )
        )
    return tuple(cases)


def _check_consistency(config: ValidationConfig) -> None:
    """Checks that the JSON Schema cannot express."""
    if not config.target.repo_path.is_dir():
        raise ConfigError(
            f"target repository not found: {config.target.repo_path}",
            remedy="run the target's bootstrap script, or fix target.repo_path",
        )
    if not (config.target.repo_path / ".git").exists():
        raise ConfigError(
            f"{config.target.repo_path} is not a git repository",
            remedy="the validator needs two git revisions and the real diff between them",
        )

    if "release" not in config.modes:
        raise ConfigError(
            "a 'release' build is required",
            remedy="the functional axis is evaluated on the release build (ADR-008)",
        )
    if "sanitized" not in config.modes:
        log.warning(
            "no 'sanitized' build configured: memory errors that do not fault "
            "the release build will go unobserved"
        )

    if config.sandbox.backend == "subprocess" and not config.sandbox.unsafe_ack:
        raise ConfigError(
            "sandbox.backend 'subprocess' provides no isolation",
            remedy="set sandbox.unsafe_ack: true to acknowledge, or use bubblewrap",
        )

    without_oracle = [case.id for case in config.tests if case.oracle is None]
    if without_oracle:
        log.warning(
            "%d test(s) have no oracle and cannot contribute to the functional "
            "axis: %s",
            len(without_oracle),
            ", ".join(without_oracle),
        )
