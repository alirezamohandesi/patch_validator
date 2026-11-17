"""Regression Test Generator — module 12 of the architecture.

Turns a confirmed, minimized, reproducible finding into a test that can be
re-run on every later build.

A generated test asserts three things, not one (SPEC 3.3, R-REG-02/03):

1. the fault **is** observed on the base build,
2. the same fault is **not** observed on the patched build,
3. the patched build satisfies the behaviour the independent oracle requires
   for this input.

The third is what stops a "fix" that simply makes the program exit early from
passing.  The oracle is inherited from the originating test case, so it still
comes from the target's specification rather than from the patched build's
output — generating a test must not quietly launder the patched behaviour
into an expectation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..analysis.crash import CrashInfo
from ..artifacts import ArtifactStore
from ..config import OracleSpec, OutputMatcher, TestCase
from ..util.hashing import sha256_bytes, short

log = logging.getLogger(__name__)

#: Version of the generated-suite format.
SUITE_VERSION = 1


@dataclass(frozen=True)
class RegressionCase:
    """One generated regression test."""

    id: str
    source_finding: str
    source_test_id: str
    build_mode: str
    input_sha256: str
    input_size: int
    input_ref: str
    expectations: dict[str, Any]
    test_case: dict[str, Any]
    case_ref: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_finding": self.source_finding,
            "source_test_id": self.source_test_id,
            "build_mode": self.build_mode,
            "input_sha256": self.input_sha256,
            "input_size": self.input_size,
            "input_ref": self.input_ref,
            "expectations": self.expectations,
            "test_case": self.test_case,
            "case_ref": self.case_ref,
            "notes": list(self.notes),
        }


class RegressionGenerator:
    """Emits runnable regression tests from confirmed findings."""

    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts
        self._cases: list[RegressionCase] = []

    @property
    def cases(self) -> tuple[RegressionCase, ...]:
        return tuple(self._cases)

    def generate(
        self,
        *,
        finding_id: str,
        case: TestCase,
        base_crash: CrashInfo,
        minimized_input: bytes,
        build_mode: str,
        reproducible: bool,
    ) -> RegressionCase | None:
        """Create a regression test for one finding.

        Returns None when the finding is not a sound basis for one: an
        unstable finding would produce a flaky test, which is worse than no
        test at all.
        """
        if not reproducible:
            log.warning(
                "not generating a regression test for %s: the finding did not "
                "replay consistently",
                finding_id,
            )
            return None

        identifier = f"regression_{case.id}_{short(sha256_bytes(minimized_input), 8)}"
        directory = f"regression/{identifier}"
        input_ref = self.artifacts.write_bytes(f"{directory}/input.bin", minimized_input)

        oracle = case.oracle
        notes: list[str] = []
        if oracle is None:
            notes.append(
                "the originating test case defines no oracle, so this test can "
                "only assert the presence and absence of the fault, not that "
                "the patched build behaves correctly for this input"
            )

        expectations: dict[str, Any] = {
            "base": {
                "must_fault": True,
                "error_type": base_crash.error_type,
                "location_signature": base_crash.location_signature,
                "location": base_crash.location,
                "detection_mechanism": base_crash.detection_mechanism,
            },
            "patched": {
                "must_fault": False,
                "oracle": _oracle_to_dict(oracle) if oracle else None,
            },
            "build_mode": build_mode,
        }

        test_case = {
            "id": identifier,
            "category": "security",
            "note": (
                f"generated from finding {finding_id}; minimized reproducer for "
                f"{base_crash.error_type} at {base_crash.location or 'unknown'}"
            ),
            "input": {"path": f"{directory}/input.bin"},
        }
        if oracle is not None:
            test_case["oracle"] = _oracle_to_dict(oracle)

        case_ref = self.artifacts.write_text(
            f"{directory}/testcase.yaml",
            yaml.safe_dump(
                {"tests": [test_case]}, sort_keys=False, default_flow_style=False
            ),
        )
        self.artifacts.write_json(f"{directory}/expectations.json", expectations)
        self.artifacts.write_text(
            f"{directory}/README.md",
            _readme(identifier, finding_id, base_crash, expectations, len(minimized_input)),
        )

        generated = RegressionCase(
            id=identifier,
            source_finding=finding_id,
            source_test_id=case.id,
            build_mode=build_mode,
            input_sha256=sha256_bytes(minimized_input),
            input_size=len(minimized_input),
            input_ref=input_ref,
            expectations=expectations,
            test_case=test_case,
            case_ref=case_ref,
            notes=tuple(notes),
        )
        self._cases.append(generated)
        log.info(
            "generated regression test %s (%d bytes) from %s",
            identifier,
            len(minimized_input),
            finding_id,
        )
        return generated

    def write_suite(self) -> str:
        """Write the consolidated suite of every generated test."""
        suite = {
            "suite_version": SUITE_VERSION,
            "cases": [case.to_dict() for case in self._cases],
        }
        return self.artifacts.write_json("regression/suite.json", suite)


def _oracle_to_dict(oracle: OracleSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": oracle.source,
        "input_validity": oracle.input_validity,
        "instructor_approved": oracle.instructor_approved,
    }
    if oracle.exit_code is not None:
        payload["exit_code"] = oracle.exit_code
    for name, matcher in (("stdout", oracle.stdout), ("stderr", oracle.stderr)):
        encoded = _matcher_to_dict(matcher)
        if encoded is not None:
            payload[name] = encoded
    if oracle.semantics:
        payload["semantics"] = oracle.semantics
    return payload


def _matcher_to_dict(matcher: OutputMatcher) -> dict[str, Any] | None:
    if matcher.match == "ignore":
        return None
    if matcher.match == "absent":
        return {"match": "absent"}
    return {"match": matcher.match, "value": matcher.value}


def _readme(
    identifier: str,
    finding_id: str,
    crash: CrashInfo,
    expectations: dict[str, Any],
    size: int,
) -> str:
    oracle = expectations["patched"]["oracle"]
    oracle_text = (
        "\n".join(f"    {key}: {value}" for key, value in oracle.items())
        if oracle
        else "    (the originating test case defined no oracle)"
    )
    return f"""# {identifier}

Generated automatically from finding `{finding_id}`.

## What it guards against

    {crash.error_type} detected by {crash.detection_mechanism}
    at {crash.location or 'an unknown location'}

The input is the minimized reproducer: {size} bytes.

## What it asserts

1. The base build still faults on this input with the recorded location
   signature `{crash.location_signature[:16]}…`. If it stops faulting, the
   test no longer guards anything and the assertion catches that.
2. The patched build does not fault on this input.
3. The patched build matches the independent oracle for this input:

{oracle_text}

Assertion 3 is the one that matters most. Without it, a change that makes the
program exit before reaching the parser would satisfy assertions 1 and 2 while
breaking the program.

## Running it

    patch-validator regression --config <config.yaml> --suite <run>/regression/suite.json

The generated test case in `testcase.yaml` can also be merged into a target
configuration, after which it runs as part of the normal matrix.
"""
