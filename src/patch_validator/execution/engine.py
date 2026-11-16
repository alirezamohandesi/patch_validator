"""Dynamic Execution Engine — module 5 of the architecture.

Runs one test input against one binary inside the sandbox and records
everything observable about it.  This is the only place in the tool where
target code executes.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..artifacts import ArtifactStore
from ..build import BuildRecord
from ..config import TestCase, ValidationConfig
from ..errors import ExecutionError
from ..sandbox import SandboxManager, SandboxRequest
from ..util.hashing import sha256_bytes
from ..util.templating import render
from .models import ExecutionResult

log = logging.getLogger(__name__)

#: Environment given to every target execution.  Deliberately minimal and
#: fixed: a target whose output depends on the ambient locale would make the
#: functional comparison meaningless.
BASE_ENV: dict[str, str] = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/work",
    "TMPDIR": "/tmp",
    "LANG": "C",
    "LC_ALL": "C",
}

#: Sanitizer defaults.  symbolize=1 and print_stacktrace=1 are what make
#: crash signatures and diff correlation possible at all; detect_leaks=0
#: keeps the run focused on the memory-safety question being asked.
ASAN_DEFAULTS = (
    "detect_leaks=0",
    "symbolize=1",
    "print_stacktrace=1",
    "handle_segv=1",
    "handle_abort=1",
    "allocator_may_return_null=1",
)
UBSAN_DEFAULTS = (
    "print_stacktrace=1",
    "halt_on_error=1",
)


class ExecutionEngine:
    """Executes test cases against built binaries, under isolation."""

    def __init__(
        self,
        config: ValidationConfig,
        sandbox: SandboxManager,
        workspace: Path,
        artifacts: ArtifactStore,
    ) -> None:
        self.config = config
        self.sandbox = sandbox
        self.workspace = workspace
        self.artifacts = artifacts

    def run_case(
        self,
        case: TestCase,
        build: BuildRecord,
        *,
        input_data: bytes | None = None,
        artifact_prefix: str | None = None,
        persist: bool = True,
    ) -> ExecutionResult:
        """Run one input against one binary.

        ``input_data`` overrides the configured input, which is what lets the
        minimizer and the reproducer replay candidate inputs through exactly
        the same path as a normal test (R-REPRO-06).
        """
        data = case.read_input() if input_data is None else input_data
        binary = Path(build.binary())
        if not binary.is_file():
            raise ExecutionError(f"binary not found: {binary}")

        workdir = self._make_workdir(case, build)
        sandbox_workdir = self.sandbox.sandbox_path(workdir)

        argv, stdin_data = self._build_invocation(data, binary, workdir, sandbox_workdir)
        env = self._build_env(build, sandbox_workdir)

        timeout = case.timeout_s or self.config.limits.timeout_s
        limits = self.config.limits

        request = SandboxRequest(
            argv=tuple(argv),
            workdir=workdir,
            # The binary stays outside the writable working directory and is
            # exposed read-only, so a target that scribbles over its own
            # directory cannot invalidate the binary hash recorded here.
            ro_binds=(binary.parent, *self.config.sandbox.extra_ro_binds),
            stdin_data=stdin_data,
            env=env,
            timeout_s=timeout,
            cpu_s=limits.cpu_s,
            memory_mb=limits.memory_mb,
            max_processes=limits.max_processes,
            max_file_size_mb=limits.max_file_size_mb,
            max_output_bytes=limits.max_output_bytes,
            network=self.config.sandbox.network,
            # A sanitizer runtime reserves a huge virtual mapping; bounding the
            # address space would abort it before main().  Sanitized builds are
            # bounded through the sanitizer's own RSS limit instead.
            apply_address_space_limit=not build.spec_is_sanitized,
        )

        log.debug("exec %s %s/%s: %s", case.id, build.version, build.mode, " ".join(argv))
        try:
            outcome = self.sandbox.run(request)
        except OSError as exc:
            raise ExecutionError(
                f"could not launch {binary.name} for test '{case.id}': {exc}"
            ) from exc

        result = ExecutionResult(
            test_id=case.id,
            version=build.version,
            build_mode=build.mode,
            exit_code=outcome.exit_code,
            signal=outcome.signal,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_s=outcome.duration_s,
            timed_out=outcome.timed_out,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            signal_inferred=outcome.signal_inferred,
            argv=tuple(argv),
            env=dict(env),
            input_sha256=sha256_bytes(data),
            input_size=len(data),
            binary_sha256=build.binary_sha256 or "",
            binary_path=str(binary),
            sandbox_backend=outcome.backend,
            sandbox_command=outcome.sandbox_command,
            rlimits=outcome.rlimits,
            timeout_s=timeout,
        )

        if persist:
            result = self._persist(result, artifact_prefix)

        shutil.rmtree(workdir, ignore_errors=True)
        return result

    # -- invocation --------------------------------------------------------

    def _make_workdir(self, case: TestCase, build: BuildRecord) -> Path:
        workdir = (
            self.workspace / "exec" / case.id / f"{build.version}.{build.mode}"
        )
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True)
        return workdir

    def _build_invocation(
        self,
        data: bytes,
        binary: Path,
        workdir: Path,
        sandbox_workdir: str,
    ) -> tuple[list[str], bytes | None]:
        """Turn an input into an argv plus optional stdin payload."""
        spec = self.config.input
        values = {
            "binary": str(binary),
            "workdir": sandbox_workdir,
        }
        stdin_data: bytes | None = None

        if spec.method == "stdin":
            stdin_data = data
        elif spec.method == "file":
            (workdir / spec.filename).write_bytes(data)
            values["input_file"] = f"{sandbox_workdir.rstrip('/')}/{spec.filename}"
        elif spec.method == "argv":
            if b"\0" in data:
                raise ExecutionError(
                    "input.method 'argv' cannot carry an input containing NUL bytes",
                )
            values["input_arg"] = data.decode("utf-8", errors="surrogateescape")

        argv = [str(binary)] + [render(arg, values) for arg in spec.argv]
        return argv, stdin_data

    def _build_env(self, build: BuildRecord, sandbox_workdir: str) -> dict[str, str]:
        env = dict(BASE_ENV)
        env["HOME"] = sandbox_workdir
        if build.spec_is_sanitized:
            env.setdefault("ASAN_OPTIONS", self._asan_options())
            env.setdefault("UBSAN_OPTIONS", ":".join(UBSAN_DEFAULTS))
        # Build-specific settings win: a target may genuinely need a different
        # sanitizer configuration.
        env.update(build.environment)
        return env

    def _asan_options(self) -> str:
        options = list(ASAN_DEFAULTS)
        options.append(f"hard_rss_limit_mb={self.config.limits.memory_mb}")
        return ":".join(options)

    # -- persistence -------------------------------------------------------

    def _persist(self, result: ExecutionResult, prefix: str | None) -> ExecutionResult:
        base = prefix or f"exec/{result.test_id}/{result.version}.{result.build_mode}"
        stdout_ref = self.artifacts.write_bytes(f"{base}/stdout.bin", result.stdout)
        stderr_ref = self.artifacts.write_bytes(f"{base}/stderr.bin", result.stderr)

        stored = ExecutionResult(
            **{
                **result.__dict__,
                "stdout_ref": stdout_ref,
                "stderr_ref": stderr_ref,
                "meta_ref": "",
            }
        )
        meta_ref = self.artifacts.write_json(f"{base}/meta.json", stored.to_dict())
        return ExecutionResult(**{**stored.__dict__, "meta_ref": meta_ref})
