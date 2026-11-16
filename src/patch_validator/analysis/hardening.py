"""Binary Hardening Analyzer — module 13 of the architecture.

Reports which exploit mitigations are present in each release binary and
whether the patch changed any of them.

Everything here is read from the ELF itself with ``readelf`` rather than
inferred from the build flags that were *requested* (SPEC 3.4): a flag that
the build system dropped, or one added by a distribution default, would make
flag-derived answers wrong in exactly the situations worth catching.

Two limits are stated in the output rather than left implicit, because the
specification calls them out:

* A PIE binary does not prove ASLR is active at runtime; that depends on the
  kernel and the execution environment.
* Evidence of a stack canary does not mean every function is protected; the
  compiler decides per function.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Status = Literal["enabled", "disabled", "partial", "full", "none", "unknown"]
ChangeStatus = Literal["unchanged", "weakened", "strengthened", "unknown"]

_READELF_TIMEOUT = 60

#: Relative strength, used to decide whether a change weakened the binary.
_STRENGTH: dict[str, int] = {
    "unknown": -1,
    "disabled": 0,
    "none": 0,
    "partial": 1,
    "enabled": 2,
    "full": 2,
}

_GNU_STACK = re.compile(r"^\s*GNU_STACK\s+(?P<rest>.*)$", re.MULTILINE)
_SEGMENT_FLAGS = re.compile(r"(?P<flags>[RWE ]{3})\s+0x[0-9a-fA-F]+\s*$")
_ELF_TYPE = re.compile(r"^\s*Type:\s+(?P<type>\w+)", re.MULTILINE)


@dataclass(frozen=True)
class BinaryHardening:
    """Mitigation status of one binary, with the evidence for each answer."""

    path: str
    nx: Status = "unknown"
    pie: Status = "unknown"
    relro: Status = "unknown"
    stack_canary: Status = "unknown"
    fortify: Status = "unknown"
    evidence: dict[str, str] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def statuses(self) -> dict[str, Status]:
        return {
            "nx": self.nx,
            "pie": self.pie,
            "relro": self.relro,
            "stack_canary": self.stack_canary,
            "fortify": self.fortify,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            **self.statuses(),
            "evidence": dict(self.evidence),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ProtectionComparison:
    name: str
    base: Status
    patched: Status
    change_status: ChangeStatus
    base_evidence: str = ""
    patched_evidence: str = ""
    warning: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "protection": self.name,
            "base": self.base,
            "patched": self.patched,
            "change_status": self.change_status,
            "base_evidence": self.base_evidence,
            "patched_evidence": self.patched_evidence,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class HardeningReport:
    base: BinaryHardening
    patched: BinaryHardening
    comparisons: tuple[ProtectionComparison, ...]
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @property
    def weakened(self) -> tuple[ProtectionComparison, ...]:
        return tuple(
            comparison
            for comparison in self.comparisons
            if comparison.change_status == "weakened"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "base": self.base.to_dict(),
            "patched": self.patched.to_dict(),
            "protections": [item.to_dict() for item in self.comparisons],
            "weakened": [item.name for item in self.weakened],
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


LIMITATIONS: tuple[str, ...] = (
    "a position-independent executable does not establish that ASLR is active "
    "at run time; that is a property of the kernel and the execution "
    "environment, not of the binary",
    "evidence of a stack canary shows the protection is in use somewhere, not "
    "that every function is protected; the compiler decides per function",
    "the absence of a mitigation here is a property of this build only, and "
    "says nothing about how the project is built elsewhere",
)


class HardeningAnalyzer:
    """Reads mitigations out of ELF binaries and compares two of them."""

    def __init__(self, readelf: str | None = None) -> None:
        self.readelf = readelf or shutil.which("readelf") or "readelf"

    @property
    def available(self) -> bool:
        return shutil.which(self.readelf) is not None or Path(self.readelf).exists()

    def analyze(self, binary: Path) -> BinaryHardening:
        errors: list[str] = []
        if not self.available:
            return BinaryHardening(
                path=str(binary),
                errors=("readelf is not installed; no ELF evidence available",),
            )
        if not binary.is_file():
            return BinaryHardening(
                path=str(binary), errors=(f"binary not found: {binary}",)
            )

        headers = self._readelf("-h", "-l", "-d", "-W", binary, errors)
        symbols = self._readelf("-s", "-W", binary, errors)
        evidence: dict[str, str] = {}

        nx = self._nx(headers, evidence)
        pie = self._pie(headers, evidence)
        relro = self._relro(headers, evidence)
        canary = self._canary(symbols, evidence)
        fortify = self._fortify(symbols, evidence)

        return BinaryHardening(
            path=str(binary),
            nx=nx,
            pie=pie,
            relro=relro,
            stack_canary=canary,
            fortify=fortify,
            evidence=evidence,
            errors=tuple(errors),
        )

    def compare(self, base: Path, patched: Path) -> HardeningReport:
        base_report = self.analyze(base)
        patched_report = self.analyze(patched)

        comparisons: list[ProtectionComparison] = []
        warnings: list[str] = []
        base_statuses = base_report.statuses()
        patched_statuses = patched_report.statuses()

        for name in base_statuses:
            before = base_statuses[name]
            after = patched_statuses[name]
            change = _change_status(before, after)
            warning = ""
            if change == "weakened":
                warning = (
                    f"{name} was {before} in the base build and is {after} in "
                    f"the patched build; a mitigation was lost"
                )
                warnings.append(warning)
            comparisons.append(
                ProtectionComparison(
                    name=name,
                    base=before,
                    patched=after,
                    change_status=change,
                    base_evidence=base_report.evidence.get(name, ""),
                    patched_evidence=patched_report.evidence.get(name, ""),
                    warning=warning,
                )
            )

        return HardeningReport(
            base=base_report,
            patched=patched_report,
            comparisons=tuple(comparisons),
            warnings=tuple(warnings),
            limitations=LIMITATIONS,
        )

    # -- individual checks -------------------------------------------------

    def _nx(self, headers: str, evidence: dict[str, str]) -> Status:
        match = _GNU_STACK.search(headers)
        if match is None:
            # No GNU_STACK segment: the loader falls back to an executable
            # stack on most targets, so this is not evidence of NX.
            evidence["nx"] = "no GNU_STACK program header"
            return "unknown"
        flags_match = _SEGMENT_FLAGS.search(match.group("rest"))
        flags = flags_match.group("flags") if flags_match else match.group("rest")
        evidence["nx"] = f"GNU_STACK flags '{flags.strip()}'"
        return "disabled" if "E" in flags else "enabled"

    def _pie(self, headers: str, evidence: dict[str, str]) -> Status:
        match = _ELF_TYPE.search(headers)
        if match is None:
            evidence["pie"] = "ELF type not reported"
            return "unknown"
        elf_type = match.group("type")
        if elf_type == "DYN":
            # A shared object and a PIE are both ET_DYN; an entry in the
            # dynamic section distinguishes a program from a library.
            pie_flag = "FLAGS_1" in headers and "PIE" in headers
            evidence["pie"] = (
                f"ELF type {elf_type}" + (", DF_1_PIE set" if pie_flag else "")
            )
            return "enabled"
        evidence["pie"] = f"ELF type {elf_type}"
        return "disabled"

    def _relro(self, headers: str, evidence: dict[str, str]) -> Status:
        has_relro = "GNU_RELRO" in headers
        bind_now = "BIND_NOW" in headers or re.search(r"FLAGS.*\bNOW\b", headers)
        if not has_relro:
            evidence["relro"] = "no GNU_RELRO segment"
            return "none"
        if bind_now:
            evidence["relro"] = "GNU_RELRO segment and BIND_NOW"
            return "full"
        evidence["relro"] = "GNU_RELRO segment without BIND_NOW"
        return "partial"

    def _canary(self, symbols: str, evidence: dict[str, str]) -> Status:
        if not symbols:
            evidence["stack_canary"] = "symbol table unavailable"
            return "unknown"
        if "__stack_chk_fail" in symbols:
            evidence["stack_canary"] = "references __stack_chk_fail"
            return "enabled"
        evidence["stack_canary"] = "no reference to __stack_chk_fail"
        return "disabled"

    def _fortify(self, symbols: str, evidence: dict[str, str]) -> Status:
        if not symbols:
            evidence["fortify"] = "symbol table unavailable"
            return "unknown"
        fortified = sorted(set(re.findall(r"\b(__\w+_chk)\b", symbols)))
        fortified = [name for name in fortified if name != "__stack_chk_fail"]
        if fortified:
            evidence["fortify"] = "fortified calls: " + ", ".join(fortified[:6])
            return "enabled"
        evidence["fortify"] = "no _chk wrappers referenced"
        return "disabled"

    # -- helpers -----------------------------------------------------------

    def _readelf(
        self, *args_and_binary: str | Path, errors: list[str] | None = None
    ) -> str:
        *flags, binary = args_and_binary
        command = [self.readelf, *[str(flag) for flag in flags], str(binary)]
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=_READELF_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
            if errors is not None:
                errors.append(f"readelf failed: {exc}")
            return ""
        if completed.returncode != 0 and errors is not None:
            errors.append(
                f"readelf {' '.join(str(flag) for flag in flags)} exited "
                f"{completed.returncode}: {completed.stderr.strip()[:200]}"
            )
        return completed.stdout


def _change_status(before: Status, after: Status) -> ChangeStatus:
    if before == "unknown" or after == "unknown":
        return "unknown"
    if before == after:
        return "unchanged"
    if _STRENGTH[after] < _STRENGTH[before]:
        return "weakened"
    return "strengthened"
