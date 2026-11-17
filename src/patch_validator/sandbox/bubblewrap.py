"""bubblewrap backend — the real isolation path.

bubblewrap creates the namespaces as an unprivileged user, so no daemon, no
socket and no elevated capability is required.  That is what lets the whole
validator run inside one ordinary CI container while still giving every single
target execution its own filesystem, process and network view
(ADR-002, R-SBX-02, R-SBX-03).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .base import ProbeReport, SandboxRequest, SandboxResult, decode_signal_exit
from .runner import execute

log = logging.getLogger(__name__)

#: System directories exposed read-only so the dynamic loader and the
#: sanitizer runtime can be found.
_SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64")

#: Individual files needed for dynamic linking.  Bound with --ro-bind-try so a
#: distribution that lacks one does not break the sandbox.
_SYSTEM_FILES = (
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/localtime",
)

#: Mount point of the working directory inside the sandbox.
SANDBOX_WORKDIR = "/work"


class BubblewrapSandboxBackend:
    """Runs each target execution inside its own set of namespaces."""

    name = "bubblewrap"

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("bwrap") or "bwrap"

    # -- capability probing ------------------------------------------------

    def probe(self) -> ProbeReport:
        """Check every capability the backend depends on.

        Reports each check separately so a failure points at the thing that is
        actually missing rather than at bubblewrap in general (R-SBX-06).
        """
        checks: dict[str, str] = {}

        if shutil.which(self.executable) is None and not Path(self.executable).exists():
            return ProbeReport(
                backend=self.name,
                available=False,
                checks={"executable": "not found"},
                reason=f"'{self.executable}' is not installed",
                remedy="install the 'bubblewrap' package",
            )
        checks["executable"] = self.executable

        checks["user_namespaces"] = _probe_user_namespaces()
        checks["cgroups_v2"] = _probe_cgroups_v2()
        checks["seccomp"] = _probe_seccomp()

        # The authoritative check: actually create the namespaces and run
        # something trivial.  Everything above is diagnostic detail for when
        # this fails.
        ok, detail = self._smoke_test()
        checks["namespace_smoke_test"] = "ok" if ok else detail
        if not ok:
            return ProbeReport(
                backend=self.name,
                available=False,
                checks=checks,
                reason=f"bubblewrap cannot create the required namespaces: {detail}",
                remedy=_remedy(checks),
            )

        return ProbeReport(backend=self.name, available=True, checks=checks)

    def _smoke_test(self) -> tuple[bool, str]:
        import subprocess

        command = [
            self.executable,
            *self._isolation_args(network=False),
            *self._filesystem_args(workdir=None, ro_binds=()),
            "--",
            "/bin/true",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=20, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if completed.returncode == 0:
            return True, "ok"
        detail = completed.stderr.strip().splitlines()
        return False, detail[-1] if detail else f"exit code {completed.returncode}"

    # -- command construction ---------------------------------------------

    def _isolation_args(self, *, network: bool) -> list[str]:
        args = [
            "--unshare-user",
            "--unshare-ipc",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--die-with-parent",
            "--new-session",
            "--hostname", "sandbox",
        ]
        if not network:
            args.append("--unshare-net")
        return args

    def _filesystem_args(
        self, *, workdir: Path | None, ro_binds: tuple[Path, ...]
    ) -> list[str]:
        args: list[str] = ["--clearenv"]

        for path in _SYSTEM_PATHS:
            entry = Path(path)
            if entry.is_symlink():
                # On usr-merged systems /lib is a symlink into /usr; recreate
                # the symlink rather than binding through it.
                args += ["--symlink", os.readlink(path), path]
            elif entry.is_dir():
                args += ["--ro-bind", path, path]

        for path in _SYSTEM_FILES:
            args += ["--ro-bind-try", path, path]

        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]

        # Caller-supplied binds come after the tmpfs so that a path underneath
        # /tmp — which is where the build workspace normally lives — is not
        # hidden by it.  bwrap applies operations in order.
        for path in ro_binds:
            args += ["--ro-bind-try", str(path), str(path)]

        if workdir is not None:
            args += ["--bind", str(workdir), SANDBOX_WORKDIR, "--chdir", SANDBOX_WORKDIR]
        else:
            args += ["--chdir", "/"]

        return args

    def build_command(self, request: SandboxRequest) -> list[str]:
        """Assemble the full bwrap command line for ``request``."""
        command = [self.executable]
        command += self._isolation_args(network=request.network)
        command += self._filesystem_args(
            workdir=request.workdir, ro_binds=request.ro_binds
        )
        for key, value in sorted(request.env.items()):
            command += ["--setenv", key, value]
        command += ["--"]
        command += self._process_limit_prefix(request)
        command += list(request.argv)
        return command

    def _process_limit_prefix(self, request: SandboxRequest) -> list[str]:
        """Apply the process-count ceiling from inside the user namespace.

        RLIMIT_NPROC is counted per real uid across the whole system, so the
        parent cannot install it without also counting every unrelated process
        the CI user already owns.  Inside the sandbox the uid is freshly mapped
        and owns nothing, so the limit means what it says.
        """
        prlimit = shutil.which("prlimit")
        if prlimit is None:
            log.debug("prlimit not found; process-count limit not enforced")
            return []
        return [prlimit, f"--nproc={request.max_processes}", "--"]

    def sandbox_path(self, host_workdir: Path) -> str:
        """The working directory is always mounted at a fixed path."""
        del host_workdir
        return SANDBOX_WORKDIR

    # -- execution ---------------------------------------------------------

    def run(self, request: SandboxRequest) -> SandboxResult:
        command = self.build_command(request)
        # The environment is installed inside the sandbox with --setenv after
        # --clearenv, so the bwrap process itself needs nothing.
        result = execute(command, request, backend=self.name, env={}, nproc=None)
        # bwrap collapses "killed by signal N" into exit code 128+N; recover it.
        return decode_signal_exit(result)


def _remedy(checks: dict[str, str]) -> str:
    """Point at the specific thing that is missing, not at bubblewrap."""
    userns = checks.get("user_namespaces", "")
    if "apparmor_restrict_unprivileged_userns" in userns:
        return (
            "this kernel allows unprivileged user namespaces only for binaries "
            "covered by an AppArmor profile, which a copy of bubblewrap inside a "
            "container is not. Run the container with "
            "--security-opt seccomp=unconfined --security-opt apparmor=unconfined "
            "--cap-add=SYS_ADMIN, or set "
            "kernel.apparmor_restrict_unprivileged_userns=0 on the host. "
            "--privileged also works but grants far more than is needed and "
            "should not be used"
        )
    if "disabled" in userns:
        return (
            f"user namespaces are {userns}; enable them on the host, or run the "
            "job somewhere that permits them"
        )
    return (
        "run the CI job in a container that permits unprivileged user namespaces, "
        "for example with --security-opt seccomp=unconfined and "
        "--security-opt apparmor=unconfined. Do not use --privileged: it is both "
        "unnecessary and far broader than needed"
    )


def _probe_user_namespaces() -> str:
    """Unprivileged user namespaces are what bubblewrap needs most."""
    max_ns = Path("/proc/sys/user/max_user_namespaces")
    if max_ns.exists():
        try:
            value = int(max_ns.read_text().strip())
        except (OSError, ValueError):
            return "unreadable"
        if value <= 0:
            return "disabled (user.max_user_namespaces = 0)"

    clone_flag = Path("/proc/sys/kernel/unprivileged_userns_clone")
    if clone_flag.exists():
        try:
            if clone_flag.read_text().strip() == "0":
                return "disabled (kernel.unprivileged_userns_clone = 0)"
        except OSError:
            return "unreadable"

    # Ubuntu 24.04 and later gate unprivileged user namespaces behind an
    # AppArmor policy.  The host's packaged bubblewrap carries a profile that
    # permits it, but a copy of bubblewrap inside a container does not, which
    # is the usual reason this works outside Docker and fails inside it.
    apparmor_gate = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    if apparmor_gate.exists():
        try:
            if apparmor_gate.read_text().strip() == "1":
                return (
                    "permitted by profile only "
                    "(kernel.apparmor_restrict_unprivileged_userns = 1)"
                )
        except OSError:
            return "unreadable"

    return "ok"


def _probe_cgroups_v2() -> str:
    """cgroups v2 is optional here; resource limits use rlimits."""
    controllers = Path("/sys/fs/cgroup/cgroup.controllers")
    if controllers.exists():
        return "available"
    return "unavailable (resource limits fall back to rlimits only)"


def _probe_seccomp() -> str:
    """A restrictive seccomp profile is the usual reason bubblewrap fails."""
    status = Path("/proc/self/status")
    if not status.exists():
        return "unknown"
    try:
        for line in status.read_text().splitlines():
            if line.startswith("Seccomp:"):
                mode = line.split()[1]
                return {
                    "0": "disabled",
                    "1": "strict",
                    "2": "filtered (container profile active)",
                }.get(mode, f"mode {mode}")
    except (OSError, IndexError):
        return "unknown"
    return "unknown"
