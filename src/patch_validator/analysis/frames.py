"""Stack frame parsing and normalisation.

Sanitizer back-traces are the only structured evidence the tool gets about
*where* a fault happened, so they feed both the crash signature and the
correlation with the patch diff.  Two things have to be handled carefully:

* The top frames are usually sanitizer interceptors and libc internals rather
  than target code.  They are kept — they are evidence — but flagged, so the
  correlation step can start from the first frame that belongs to the program
  under test.
* Base and patched are built in different worktrees, so absolute paths differ
  for identical code.  Paths are normalised against the known source roots
  before anything compares them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: ``    #3 0x55a1b2c3 in handle_text /src/record.c:30:9``
_FRAME = re.compile(r"^\s*#(?P<index>\d+)\s+0x(?P<address>[0-9a-fA-F]+)\s+(?P<rest>.*)$")

#: ``(/lib/x86_64-linux-gnu/libc.so.6+0x2a28b)``
_MODULE = re.compile(r"^\((?P<module>[^()]+)\+0x(?P<offset>[0-9a-fA-F]+)\)$")

#: ``/src/record.c:30:9`` or ``/src/record.c:30``
_LOCATION = re.compile(r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<column>\d+))?$")

#: Path fragments that mark a frame as sanitizer or toolchain machinery.
_INTERCEPTOR_MARKERS = (
    "/libsanitizer/",
    "sanitizer_common",
    "/compiler-rt/",
    "_fortified.h",
    "/sysdeps/",
    "/csu/",
)

#: Symbols that are libc entry or wrapper frames rather than target code.
_INTERCEPTOR_SYMBOLS = frozenset(
    {
        "__libc_start_main",
        "__libc_start_call_main",
        "_start",
        "__interceptor_memcpy",
        "__interceptor_memset",
        "__interceptor_strcpy",
        "__asan_memcpy",
        "__asan_report_store1",
    }
)


@dataclass(frozen=True)
class StackFrame:
    index: int
    address: str = ""
    function: str = ""
    file: str = ""
    line: int | None = None
    column: int | None = None
    module: str = ""
    offset: str = ""
    raw: str = ""

    @property
    def is_interceptor(self) -> bool:
        """Whether this frame is toolchain machinery rather than target code."""
        if self.function in _INTERCEPTOR_SYMBOLS:
            return True
        haystack = f"{self.file} {self.module}"
        return any(marker in haystack for marker in _INTERCEPTOR_MARKERS)

    @property
    def has_source(self) -> bool:
        return bool(self.file) and self.line is not None

    def location(self) -> str:
        if self.has_source:
            return f"{self.file}:{self.line}"
        if self.module:
            return f"{self.module}+0x{self.offset}"
        return self.function or f"0x{self.address}"

    def describe(self) -> str:
        return f"#{self.index} {self.function or '??'} {self.location()}"

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "address": self.address,
            "function": self.function,
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "module": self.module,
            "offset": self.offset,
            "is_interceptor": self.is_interceptor,
        }


def parse_frames(text: str) -> list[StackFrame]:
    """Extract every ``#N 0xADDR ...`` frame from sanitizer output."""
    frames: list[StackFrame] = []
    for raw_line in text.splitlines():
        match = _FRAME.match(raw_line)
        if match is None:
            continue
        frames.append(
            _parse_frame(
                index=int(match.group("index")),
                address=match.group("address"),
                rest=match.group("rest").strip(),
                raw=raw_line.strip(),
            )
        )
    return frames


def _parse_frame(*, index: int, address: str, rest: str, raw: str) -> StackFrame:
    function = ""
    if rest.startswith("in "):
        rest = rest[3:].strip()
        function, rest = _split_trailing_location(rest)

    file = ""
    line: int | None = None
    column: int | None = None
    module = ""
    offset = ""

    module_match = _MODULE.match(rest)
    if module_match is not None:
        module = module_match.group("module")
        offset = module_match.group("offset")
    elif rest:
        location_match = _LOCATION.match(rest)
        if location_match is not None:
            file = location_match.group("file")
            line = int(location_match.group("line"))
            column_text = location_match.group("column")
            column = int(column_text) if column_text else None
        else:
            file = rest

    return StackFrame(
        index=index,
        address=address,
        function=function,
        file=file,
        line=line,
        column=column,
        module=module,
        offset=offset,
        raw=raw,
    )


def _split_trailing_location(rest: str) -> tuple[str, str]:
    """Split ``func name path:line`` into the function and the location.

    The function name is taken as everything before the final whitespace-
    separated token when that token looks like a source location or a module
    offset.  C++ symbols contain spaces, so splitting on the first space would
    truncate them.
    """
    if not rest:
        return "", ""
    head, separator, tail = rest.rpartition(" ")
    if not separator:
        return rest, ""
    if _MODULE.match(tail) or _LOCATION.match(tail) or tail.startswith("/"):
        return head.strip(), tail.strip()
    return rest, ""


def normalize_path(path: str, source_roots: tuple[Path, ...] = ()) -> str:
    """Make a frame's file path comparable across builds.

    Paths under a known source root become relative to it, which is what makes
    the base worktree and the patched worktree produce the same text for the
    same file.  Anything else keeps only its basename, since absolute
    toolchain paths carry no information worth comparing.
    """
    if not path:
        return ""
    candidate = Path(path)
    for root in source_roots:
        try:
            return str(candidate.resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            continue
    if candidate.is_absolute() or path.startswith(".."):
        return candidate.name
    return path


def target_frames(
    frames: list[StackFrame], source_roots: tuple[Path, ...] = ()
) -> list[StackFrame]:
    """Frames that belong to the program under test.

    Falls back to all non-interceptor frames when no source root matches,
    which keeps the tool useful for a target built outside a worktree.
    """
    if source_roots:
        inside = [frame for frame in frames if _within(frame.file, source_roots)]
        if inside:
            return inside
    return [frame for frame in frames if not frame.is_interceptor]


def _within(path: str, roots: tuple[Path, ...]) -> bool:
    if not path:
        return False
    try:
        resolved = Path(path).resolve()
    except OSError:  # pragma: no cover - defensive
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False
