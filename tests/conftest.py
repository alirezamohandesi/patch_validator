"""Shared fixtures and factories.

The analysis modules take plain dataclasses, so most tests can build exactly
the observation they want to reason about without running anything.  Tests
that genuinely need a compiler, a sandbox or the toy repository say so with a
marker and skip cleanly when the requirement is missing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from patch_validator.analysis.crash import CrashAnalyzer, CrashInfo
from patch_validator.config.models import (
    Limits,
    OracleSpec,
    OutputMatcher,
    TestCase,
)
from patch_validator.execution import ExecutionResult

REPO_ROOT = Path(__file__).resolve().parent.parent
TOY_ROOT = REPO_ROOT / "targets" / "recparse"
TOY_REPO = TOY_ROOT / "repo"
CONFIG = REPO_ROOT / "configs" / "recparse.yaml"


def pytest_collection_modifyitems(config, items):
    """Skip marked tests when their requirement is not available."""
    del config
    toolchain_missing = shutil.which("gcc") is None or shutil.which("cmake") is None
    sandbox_missing = shutil.which("bwrap") is None
    repo_missing = not (TOY_REPO / ".git").exists()

    for item in items:
        if "toolchain" in item.keywords and toolchain_missing:
            item.add_marker(pytest.mark.skip(reason="gcc and cmake are required"))
        if "sandbox" in item.keywords and sandbox_missing:
            item.add_marker(pytest.mark.skip(reason="bubblewrap is required"))
        if ("slow" in item.keywords or "toolchain" in item.keywords) and repo_missing:
            item.add_marker(
                pytest.mark.skip(
                    reason="run targets/recparse/bootstrap.sh to create the target repo"
                )
            )


@pytest.fixture(scope="session")
def toy_repo() -> Path:
    """The materialised toy target repository."""
    if not (TOY_REPO / ".git").exists():
        pytest.skip("run targets/recparse/bootstrap.sh first")
    return TOY_REPO


@pytest.fixture(scope="session")
def toy_config_path() -> Path:
    return CONFIG


@pytest.fixture
def limits() -> Limits:
    return Limits(timeout_s=5, memory_mb=512, cpu_s=5, max_processes=32)


def make_result(
    *,
    test_id: str = "t",
    version: str = "base",
    build_mode: str = "sanitized",
    exit_code: int | None = 0,
    signal: int | None = None,
    stdout: bytes = b"",
    stderr: bytes = b"",
    timed_out: bool = False,
    signal_inferred: bool = False,
    timeout_s: float = 10.0,
) -> ExecutionResult:
    """Build an ExecutionResult without running anything."""
    return ExecutionResult(
        test_id=test_id,
        version=version,  # type: ignore[arg-type]
        build_mode=build_mode,  # type: ignore[arg-type]
        exit_code=exit_code,
        signal=signal,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.01,
        timed_out=timed_out,
        stdout_truncated=False,
        stderr_truncated=False,
        signal_inferred=signal_inferred,
        argv=("/bin/target", "input.bin"),
        env={},
        input_sha256="0" * 64,
        input_size=0,
        binary_sha256="1" * 64,
        binary_path="/bin/target",
        sandbox_backend="bubblewrap",
        sandbox_command=("bwrap", "--", "/bin/target"),
        rlimits={},
        timeout_s=timeout_s,
        stdout_ref="exec/stdout.bin",
        stderr_ref="exec/stderr.bin",
    )


def analyze(result: ExecutionResult, roots: tuple[Path, ...] = ()) -> CrashInfo:
    return CrashAnalyzer(source_roots=roots).analyze(result)


def make_case(
    test_id: str = "t",
    *,
    category: str = "valid",
    exit_code: int | None = 0,
    stdout: OutputMatcher | None = None,
    stderr: OutputMatcher | None = None,
    with_oracle: bool = True,
) -> TestCase:
    oracle = (
        OracleSpec(
            source="specification",
            input_validity="valid",
            exit_code=exit_code,
            stdout=stdout or OutputMatcher(),
            stderr=stderr or OutputMatcher(),
        )
        if with_oracle
        else None
    )
    return TestCase(
        id=test_id,
        category=category,  # type: ignore[arg-type]
        input_inline=b"payload",
        oracle=oracle,
    )


#: A real AddressSanitizer report, captured from the toy target's base build.
ASAN_STACK_OVERFLOW = """=================================================================
==10578==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x76c677f00040 at pc 0x63bab6446c88 bp 0x7ffc19609e40 sp 0x7ffc19609e30
WRITE of size 1 at 0x76c677f00040 thread T0
    #0 0x63bab6446c87 in copy_payload /work/src/base/src/record.c:22
    #1 0x63bab644723e in handle_text /work/src/base/src/record.c:30
    #2 0x63bab644723e in parse_stream /work/src/base/src/record.c:102
    #3 0x63bab6446a35 in main /work/src/base/src/main.c:78
    #4 0x76c67a22a1c9 in __libc_start_call_main ../sysdeps/nptl/libc_start_call_main.h:58
SUMMARY: AddressSanitizer: stack-buffer-overflow /work/src/base/src/record.c:22 in copy_payload
"""

ASAN_USE_AFTER_FREE = """==123==ERROR: AddressSanitizer: heap-use-after-free on address 0x602000000010 at pc 0x4008f1
READ of size 4 at 0x602000000010 thread T0
    #0 0x4008f0 in use_it /src/app.c:17
    #1 0x400950 in main /src/app.c:30
"""

UBSAN_OVERFLOW = (
    "/src/app.c:12:9: runtime error: signed integer overflow: "
    "2147483647 + 1 cannot be represented in type 'int'\n"
)

FORTIFY_ABORT = "*** buffer overflow detected ***: terminated\n"
STACK_SMASH = "*** stack smashing detected ***: terminated\n"


def have_tool(name: str) -> bool:
    return shutil.which(name) is not None


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout
