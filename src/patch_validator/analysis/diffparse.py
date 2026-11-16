"""Unified diff parsing.

The validator must be able to say *which lines the patch touched*, separately
for the pre-patch and the post-patch side of each file.  A fault observed on
the base build has line numbers from the old file; the same fault observed on
the patched build has line numbers from the new file.  Conflating the two
would make every correlation off by the size of the patch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FileStatus = Literal["added", "deleted", "modified", "renamed", "binary"]

_DIFF_HEADER = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$")
_OLD_FILE = re.compile(r"^--- (?:a/)?(?P<path>.*)$")
_NEW_FILE = re.compile(r"^\+\+\+ (?:b/)?(?P<path>.*)$")
_HUNK = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))?"
    r" \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<context>.*)$"
)


@dataclass(frozen=True)
class Hunk:
    """One ``@@`` block, with the touched lines on each side resolved."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    #: Trailing text of the @@ header; git usually puts the enclosing
    #: function there, which is a useful hint but never treated as proof.
    context: str
    lines: tuple[str, ...]
    #: Line numbers in the OLD file that this hunk deleted or replaced.
    removed_lines: tuple[int, ...]
    #: Line numbers in the NEW file that this hunk added.
    added_lines: tuple[int, ...]
    #: OLD line numbers that added lines were inserted in front of.  A pure
    #: insertion deletes nothing, so without this a patch that only adds code
    #: would appear to touch no line of the pre-patch file at all — and a
    #: fault observed on the base build could never be tied to it.
    insertion_points: tuple[int, ...] = ()
    #: NEW line numbers that deleted lines used to sit in front of.
    deletion_points: tuple[int, ...] = ()

    @property
    def old_range(self) -> tuple[int, int]:
        """Inclusive span this hunk covers in the old file, context included."""
        if self.old_count == 0:
            return (self.old_start, self.old_start)
        return (self.old_start, self.old_start + self.old_count - 1)

    @property
    def new_range(self) -> tuple[int, int]:
        if self.new_count == 0:
            return (self.new_start, self.new_start)
        return (self.new_start, self.new_start + self.new_count - 1)

    def changed_lines(self, side: Literal["old", "new"]) -> set[int]:
        """Lines of one side that this hunk changed, insertion points included."""
        if side == "old":
            return {*self.removed_lines, *self.insertion_points}
        return {*self.added_lines, *self.deletion_points}

    def touches(self, line: int, *, side: Literal["old", "new"]) -> bool:
        """Whether ``line`` is one of the lines this hunk actually changed."""
        return line in self.changed_lines(side)

    def within(self, line: int, *, side: Literal["old", "new"]) -> bool:
        """Whether ``line`` falls inside the hunk's span, context included."""
        start, end = self.old_range if side == "old" else self.new_range
        return start <= line <= end

    def header(self) -> str:
        return (
            f"@@ -{self.old_start},{self.old_count} "
            f"+{self.new_start},{self.new_count} @@{self.context}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "header": self.header(),
            "context": self.context.strip(),
            "old_range": list(self.old_range),
            "new_range": list(self.new_range),
            "removed_lines": list(self.removed_lines),
            "added_lines": list(self.added_lines),
            "insertion_points": sorted(set(self.insertion_points)),
            "deletion_points": sorted(set(self.deletion_points)),
            "text": "\n".join(self.lines),
        }


@dataclass(frozen=True)
class FileDiff:
    old_path: str
    new_path: str
    status: FileStatus
    hunks: tuple[Hunk, ...]

    @property
    def path(self) -> str:
        """The path to report; the new one unless the file was deleted."""
        return self.old_path if self.status == "deleted" else self.new_path

    def paths(self) -> set[str]:
        return {path for path in (self.old_path, self.new_path) if path}

    def changed_lines(self, side: Literal["old", "new"]) -> set[int]:
        lines: set[int] = set()
        for hunk in self.hunks:
            lines.update(hunk.changed_lines(side))
        return lines

    def to_dict(self) -> dict[str, object]:
        return {
            "old_path": self.old_path,
            "new_path": self.new_path,
            "status": self.status,
            "hunks": [hunk.to_dict() for hunk in self.hunks],
        }


@dataclass(frozen=True)
class PatchDiff:
    files: tuple[FileDiff, ...]
    raw: str

    def file_for(self, path: str) -> FileDiff | None:
        """Exact path lookup against either side of the diff."""
        for entry in self.files:
            if path in entry.paths():
                return entry
        return None

    def file_by_basename(self, name: str) -> FileDiff | None:
        """Fallback lookup, used only when it is unambiguous.

        A target whose build emits relative or stripped paths can leave a
        frame with nothing but a file name.  Matching on that is acceptable
        evidence only when exactly one changed file carries the name.
        """
        matches = [
            entry
            for entry in self.files
            if any(path.rsplit("/", 1)[-1] == name for path in entry.paths())
        ]
        return matches[0] if len(matches) == 1 else None

    @property
    def is_empty(self) -> bool:
        return not self.files

    def summary(self) -> str:
        hunks = sum(len(entry.hunks) for entry in self.files)
        return f"{len(self.files)} file(s), {hunks} hunk(s)"

    def to_dict(self) -> dict[str, object]:
        return {
            "files": [entry.to_dict() for entry in self.files],
            "file_count": len(self.files),
            "hunk_count": sum(len(entry.hunks) for entry in self.files),
        }


def parse_patch(text: str) -> PatchDiff:
    """Parse a unified diff produced by ``git diff``."""
    files: list[FileDiff] = []
    lines = text.splitlines()
    index = 0
    total = len(lines)

    while index < total:
        header = _DIFF_HEADER.match(lines[index])
        if header is None:
            index += 1
            continue

        old_path = header.group("old")
        new_path = header.group("new")
        status: FileStatus = "modified"
        index += 1

        # Extended header lines sit between the "diff --git" line and the
        # first hunk; they are what distinguishes an added file from a
        # modified one, and a binary file from a textual one.
        while index < total and not lines[index].startswith("@@"):
            line = lines[index]
            if line.startswith("diff --git "):
                break
            if line.startswith("new file mode"):
                status = "added"
            elif line.startswith("deleted file mode"):
                status = "deleted"
            elif line.startswith("rename from") or line.startswith("rename to"):
                status = "renamed"
            elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
                status = "binary"
            elif (match := _OLD_FILE.match(line)) is not None:
                path = match.group("path")
                old_path = "" if path == "/dev/null" else path
            elif (match := _NEW_FILE.match(line)) is not None:
                path = match.group("path")
                new_path = "" if path == "/dev/null" else path
            index += 1

        hunks: list[Hunk] = []
        while index < total and lines[index].startswith("@@"):
            hunk, index = _parse_hunk(lines, index)
            hunks.append(hunk)

        files.append(
            FileDiff(
                old_path=old_path,
                new_path=new_path,
                status=status,
                hunks=tuple(hunks),
            )
        )

    return PatchDiff(files=tuple(files), raw=text)


def _parse_hunk(lines: list[str], index: int) -> tuple[Hunk, int]:
    match = _HUNK.match(lines[index])
    assert match is not None
    old_start = int(match.group("old_start"))
    old_count = int(match.group("old_count") or 1)
    new_start = int(match.group("new_start"))
    new_count = int(match.group("new_count") or 1)
    context = match.group("context")

    body: list[str] = []
    removed: list[int] = []
    added: list[int] = []
    insertion_points: list[int] = []
    deletion_points: list[int] = []
    old_line = old_start
    new_line = new_start
    index += 1

    while index < len(lines):
        line = lines[index]
        if line.startswith("@@") or line.startswith("diff --git "):
            break
        if line.startswith("\\"):
            # "\ No newline at end of file" belongs to the previous line.
            body.append(line)
            index += 1
            continue

        marker = line[:1]
        if marker == "+":
            added.append(new_line)
            insertion_points.append(old_line)
            new_line += 1
        elif marker == "-":
            removed.append(old_line)
            deletion_points.append(new_line)
            old_line += 1
        elif marker in (" ", ""):
            old_line += 1
            new_line += 1
        else:
            # Anything else ends the hunk; git does not emit it.
            break

        body.append(line)
        index += 1

    return (
        Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            context=context,
            lines=tuple(body),
            removed_lines=tuple(removed),
            added_lines=tuple(added),
            insertion_points=tuple(dict.fromkeys(insertion_points)),
            deletion_points=tuple(dict.fromkeys(deletion_points)),
        ),
        index,
    )
