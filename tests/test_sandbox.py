"""Sandbox verification.

The specification's amendment lists exactly what has to be demonstrated about
the sandbox: that it runs inside a container, that it blocks access to files
outside itself, that the network is unreachable, that timeouts and resource
limits are enforced, that processes are cleaned up afterwards, that
consecutive runs are independent, and that evidence survives the sandbox being
torn down.  There is one test here per item on that list.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from patch_validator.config.models import SandboxSpec
from patch_validator.errors import SandboxUnavailable
from patch_validator.sandbox import SandboxManager, SandboxRequest

pytestmark = pytest.mark.sandbox

SH = "/bin/sh"


@pytest.fixture
def manager() -> SandboxManager:
    manager = SandboxManager(SandboxSpec(backend="bubblewrap"))
    if not manager.probe().available:
        pytest.skip("bubblewrap cannot create namespaces here")
    return manager


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


def run(manager: SandboxManager, workdir: Path, script: str, **kwargs):
    request = SandboxRequest(
        argv=(SH, "-c", script),
        workdir=workdir,
        timeout_s=kwargs.pop("timeout_s", 10.0),
        **kwargs,
    )
    return manager.run(request)


class TestIsolation:
    def test_host_home_is_not_visible(self, manager, workdir):
        result = run(manager, workdir, "ls /home 2>&1; echo done")
        assert b"done" in result.stdout
        assert b"No such file" in result.stdout or result.stdout.strip() == b"done"

    def test_a_secret_outside_the_workdir_is_unreachable(self, manager, workdir, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("classified")
        result = run(manager, workdir, f"cat {secret} 2>&1")
        assert b"classified" not in result.stdout

    def test_etc_shadow_is_unreachable(self, manager, workdir):
        result = run(manager, workdir, "cat /etc/shadow 2>&1")
        assert b"root:" not in result.stdout

    def test_the_working_directory_is_writable(self, manager, workdir):
        result = run(manager, workdir, "echo written > out.txt; cat out.txt")
        assert result.stdout.strip() == b"written"
        assert (workdir / "out.txt").read_text().strip() == "written"

    def test_the_network_is_unreachable(self, manager, workdir):
        result = run(
            manager,
            workdir,
            "getent hosts example.com >/dev/null 2>&1 && echo NET || echo NONET",
        )
        assert result.stdout.strip() == b"NONET"

    def test_the_process_table_is_private(self, manager, workdir):
        result = run(manager, workdir, "ls -d /proc/[0-9]* | wc -l")
        # A fresh PID namespace shows only this tiny process tree, never the
        # hundreds of processes on the host.
        assert int(result.stdout.strip()) < 15

    def test_the_binary_is_exposed_read_only(self, manager, workdir, tmp_path):
        tool_dir = tmp_path / "bin"
        tool_dir.mkdir()
        shutil.copy(SH, tool_dir / "sh")
        request = SandboxRequest(
            argv=(str(tool_dir / "sh"), "-c", f"echo x > {tool_dir / 'sh'} 2>&1; echo rc=$?"),
            workdir=workdir,
            ro_binds=(tool_dir,),
            timeout_s=10,
        )
        result = manager.run(request)
        assert b"rc=0" not in result.stdout


class TestLimits:
    def test_a_hang_is_killed_at_the_timeout(self, manager, workdir):
        started = time.monotonic()
        result = run(manager, workdir, "sleep 60", timeout_s=2.0)
        elapsed = time.monotonic() - started
        assert result.timed_out
        assert elapsed < 10
        assert result.signal is not None

    def test_a_fork_bomb_cannot_exhaust_the_host(self, manager, workdir):
        result = run(
            manager,
            workdir,
            "i=0; while [ $i -lt 300 ]; do sleep 5 & i=$((i+1)); done; echo spawned",
            timeout_s=15.0,
            max_processes=16,
        )
        assert b"spawned" not in result.stdout

    def test_output_is_capped_and_the_truncation_is_recorded(self, manager, workdir):
        result = run(
            manager,
            workdir,
            "head -c 10000000 /dev/zero",
            timeout_s=20.0,
            max_output_bytes=4096,
        )
        assert len(result.stdout) == 4096
        assert result.stdout_truncated

    def test_the_address_space_limit_is_enforced(self, manager, workdir):
        result = run(
            manager,
            workdir,
            # Allocating far beyond the limit must fail rather than succeed.
            "dd if=/dev/zero of=/dev/null bs=256M count=1 2>&1; echo rc=$?",
            timeout_s=15.0,
            memory_mb=64,
        )
        assert b"rc=0" not in result.stdout

    def test_limits_are_reported_with_the_result(self, manager, workdir):
        result = run(manager, workdir, "true")
        assert "RLIMIT_CPU" in result.rlimits
        assert "RLIMIT_NPROC" in result.rlimits


class TestLifecycle:
    def test_no_process_survives_the_run(self, manager, workdir):
        marker = f"pv-marker-{os.getpid()}"
        run(
            manager,
            workdir,
            f"sleep 120 & echo {marker}; exit 0",
            timeout_s=5.0,
        )
        time.sleep(0.5)
        survivors = [
            entry
            for entry in Path("/proc").iterdir()
            if entry.name.isdigit() and _cmdline(entry).startswith("sleep\x00120")
        ]
        assert not survivors

    def test_consecutive_runs_do_not_leak_state(self, manager, workdir):
        run(manager, workdir, "echo first > /tmp/leak.txt")
        result = run(manager, workdir, "cat /tmp/leak.txt 2>&1; echo done")
        assert b"first" not in result.stdout

    def test_evidence_outlives_the_sandbox(self, manager, workdir):
        result = run(manager, workdir, "echo stdout-text; echo stderr-text >&2")
        shutil.rmtree(workdir, ignore_errors=True)
        # Output was captured on the host side, so tearing the sandbox down
        # cannot take the evidence with it.
        assert result.stdout.strip() == b"stdout-text"
        assert result.stderr.strip() == b"stderr-text"

    def test_exit_codes_and_signals_are_distinguished(self, manager, workdir):
        assert run(manager, workdir, "exit 7").exit_code == 7
        killed = run(manager, workdir, "kill -SEGV $$")
        assert killed.signal is not None
        assert killed.signal_name == "SIGSEGV"


class TestBackendSelection:
    def test_the_unisolated_backend_must_be_acknowledged(self):
        manager = SandboxManager(SandboxSpec(backend="subprocess", unsafe_ack=False))
        with pytest.raises(SandboxUnavailable, match="no isolation"):
            manager.ensure_available()

    def test_an_acknowledged_unisolated_backend_still_labels_itself(self, workdir):
        manager = SandboxManager(SandboxSpec(backend="subprocess", unsafe_ack=True))
        result = run(manager, workdir, "echo hello")
        assert result.backend == "subprocess"
        assert result.stdout.strip() == b"hello"

    def test_the_probe_reports_each_capability_separately(self, manager):
        probe = manager.probe()
        assert "user_namespaces" in probe.checks
        assert "namespace_smoke_test" in probe.checks
        assert "seccomp" in probe.checks


def _cmdline(entry: Path) -> str:
    try:
        return (entry / "cmdline").read_text()
    except OSError:
        return ""
