"""Process launching shared by the sandbox backends.

Both backends need the same careful handling around a child that is expected
to crash, hang or fork: resource limits installed before ``execve``, its own
session so the whole process group can be killed, output captured into host
files the child cannot reopen, and a hard timeout.
"""

from __future__ import annotations

import logging
import os
import resource
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .base import SandboxRequest, SandboxResult

log = logging.getLogger(__name__)

_MB = 1024 * 1024

#: Grace period between SIGKILL to the group and giving up on the reaper.
_REAP_TIMEOUT = 5.0


def build_rlimits(request: SandboxRequest, *, nproc: int | None) -> dict[str, str]:
    """Human-readable description of the limits that will be installed."""
    limits = {
        "RLIMIT_CPU": f"{request.cpu_s}s",
        "RLIMIT_FSIZE": f"{request.max_file_size_mb}MB",
        "RLIMIT_CORE": "0",
    }
    if nproc is None:
        # RLIMIT_NPROC counts every process owned by the real uid, not just
        # the ones in this tree, so it cannot be installed from the parent.
        # The bubblewrap backend applies it inside the user namespace instead,
        # where the mapped uid starts out with no processes at all.
        limits["RLIMIT_NPROC"] = f"{request.max_processes} (applied inside the sandbox)"
    else:
        limits["RLIMIT_NPROC"] = str(nproc)
    if request.apply_address_space_limit:
        limits["RLIMIT_AS"] = f"{request.memory_mb}MB"
    else:
        limits["RLIMIT_AS"] = "unset (sanitizer build)"
    return limits


def _preexec(request: SandboxRequest, nproc: int | None) -> Callable[[], None]:
    """Build the pre-exec hook that installs limits in the child.

    Resource limits survive both ``execve`` and ``clone``, so limits installed
    here still bound the target even though the immediate child is the sandbox
    helper rather than the target itself.
    """

    def apply() -> None:
        # Own session: lets the parent kill the entire process tree even if the
        # target forks before it hangs.
        os.setsid()

        def limit(what: int, soft: int, hard: int | None = None) -> None:
            try:
                resource.setrlimit(what, (soft, hard if hard is not None else soft))
            except (ValueError, OSError):
                # A limit we cannot lower is reported by build_rlimits as
                # requested; failing the whole execution here would be worse.
                pass

        limit(resource.RLIMIT_CPU, request.cpu_s, request.cpu_s + 1)
        limit(resource.RLIMIT_FSIZE, request.max_file_size_mb * _MB)
        limit(resource.RLIMIT_CORE, 0)
        if nproc is not None:
            limit(resource.RLIMIT_NPROC, nproc)
        if request.apply_address_space_limit:
            limit(resource.RLIMIT_AS, request.memory_mb * _MB)

    return apply


def _read_capped(path: Path, cap: int) -> tuple[bytes, bool]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(cap)
    return data, size > cap


def execute(
    command: list[str],
    request: SandboxRequest,
    *,
    backend: str,
    env: dict[str, str],
    nproc: int | None = None,
) -> SandboxResult:
    """Run ``command``, enforcing the limits described by ``request``.

    ``nproc`` is the process-count limit to install from the parent, or None
    when the backend installs it itself after entering a user namespace.
    """
    # Output goes to host files outside any bind mount, passed as inherited
    # file descriptors.  The child can write to them but cannot reopen,
    # truncate or replace them.
    with tempfile.TemporaryDirectory(prefix="pv-io-") as capture_dir:
        out_path = Path(capture_dir) / "stdout"
        err_path = Path(capture_dir) / "stderr"

        started = time.monotonic()
        timed_out = False

        with out_path.open("wb") as out_file, err_path.open("wb") as err_file:
            try:
                process = subprocess.Popen(  # noqa: S603 - argv list, no shell
                    command,
                    stdin=subprocess.PIPE,
                    stdout=out_file,
                    stderr=err_file,
                    env=env,
                    cwd=str(request.workdir),
                    preexec_fn=_preexec(request, nproc),
                    close_fds=True,
                )
            except OSError as exc:
                raise OSError(f"cannot launch {command[0]}: {exc}") from exc

            try:
                process.communicate(
                    input=request.stdin_data, timeout=request.timeout_s
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(process)
                try:
                    process.communicate(timeout=_REAP_TIMEOUT)
                except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                    log.error("process %d survived SIGKILL", process.pid)
            except BrokenPipeError:
                # The target exited without draining stdin; normal for a crash.
                process.wait(timeout=_REAP_TIMEOUT)

        duration = time.monotonic() - started
        returncode = process.returncode

        # Even after the leader exits, forked children may still hold the
        # session.  Sweeping the group keeps one test from leaking processes
        # into the next.
        _kill_group(process, quiet=True)

        stdout, stdout_truncated = _read_capped(out_path, request.max_output_bytes)
        stderr, stderr_truncated = _read_capped(err_path, request.max_output_bytes)

    exit_code: int | None
    signal_number: int | None
    if returncode is not None and returncode < 0:
        exit_code, signal_number = None, -returncode
    else:
        exit_code, signal_number = returncode, None

    return SandboxResult(
        argv=request.argv,
        exit_code=exit_code,
        signal=signal_number,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration,
        timed_out=timed_out,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        backend=backend,
        sandbox_command=tuple(command),
        rlimits=build_rlimits(request, nproc=nproc),
    )


def _kill_group(process: subprocess.Popen[bytes], *, quiet: bool = False) -> None:
    """Kill the child's whole process group."""
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError as exc:  # pragma: no cover - defensive
        if not quiet:
            log.warning("could not kill process group of %d: %s", process.pid, exc)
