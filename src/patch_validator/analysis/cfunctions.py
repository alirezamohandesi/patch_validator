"""Mapping source lines to enclosing functions.

Correlating a fault with a patch at *file* granularity is too coarse to be
evidence — the specification says so explicitly.  Function granularity needs a
line-to-function map, and building one without a full C parser means a
heuristic.  The heuristic is deliberately conservative: when it cannot
confidently name the function containing a line it returns nothing, and the
correlation degrades to the weaker file-level claim rather than inventing a
function name.

Approach: blank out comments and literals so braces inside them cannot be
miscounted, then walk the text tracking brace depth.  Every transition from
depth 0 to depth 1 is a candidate definition; the declarator text immediately
before the brace supplies the name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Words that can precede "(" without the construct being a function.
_NOT_FUNCTIONS = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "return",
        "sizeof",
        "typedef",
        "struct",
        "union",
        "enum",
        "class",
        "namespace",
        "extern",
        "static_assert",
        "_Static_assert",
        "catch",
        "__attribute__",
        "alignof",
        "_Alignof",
        "decltype",
        "noexcept",
    }
)

#: Trailing ``name(`` of a declarator, allowing qualified C++ names.
_DECLARATOR = re.compile(r"(?P<name>[A-Za-z_~][A-Za-z0-9_:~]*)\s*\([^()]*\)[^()]*$")


@dataclass(frozen=True)
class FunctionRange:
    name: str
    start_line: int
    end_line: int

    def contains(self, line: int) -> bool:
        return self.start_line <= line <= self.end_line

    def overlaps(self, lines: set[int]) -> bool:
        return any(self.contains(line) for line in lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


def blank_noncode(source: str) -> str:
    """Replace comment and literal contents with spaces, keeping offsets.

    Keeping the length and the newlines identical means line numbers computed
    on the blanked text are still valid for the original.
    """
    out: list[str] = []
    index = 0
    length = len(source)
    state: str | None = None  # None | "line" | "block" | '"' | "'"

    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""

        if state is None:
            if char == "/" and following == "/":
                state = "line"
                out.append("  ")
                index += 2
                continue
            if char == "/" and following == "*":
                state = "block"
                out.append("  ")
                index += 2
                continue
            if char in ('"', "'"):
                state = char
                out.append(char)
                index += 1
                continue
            out.append(char)
            index += 1
            continue

        if state == "line":
            if char == "\n":
                state = None
                out.append("\n")
            else:
                out.append(" ")
            index += 1
            continue

        if state == "block":
            if char == "*" and following == "/":
                state = None
                out.append("  ")
                index += 2
                continue
            out.append("\n" if char == "\n" else " ")
            index += 1
            continue

        # Inside a string or character literal.
        if char == "\\" and following:
            out.append("  " if following != "\n" else " \n")
            index += 2
            continue
        if char == state:
            state = None
            out.append(char)
            index += 1
            continue
        out.append("\n" if char == "\n" else " ")
        index += 1

    return "".join(out)


def extract_functions(source: str) -> tuple[FunctionRange, ...]:
    """Find every function definition and the line span it occupies."""
    blanked = blank_noncode(source)
    line_starts = _line_starts(blanked)

    functions: list[FunctionRange] = []
    depth = 0
    body_start: int | None = None
    pending_name: str | None = None
    segment_start = 0  # offset just past the last ';', '}' or '{'

    for offset, char in enumerate(blanked):
        if char == "{":
            if depth == 0:
                declarator = blanked[segment_start:offset]
                pending_name = _declarator_name(declarator)
                body_start = offset
            depth += 1
            segment_start = offset + 1
        elif char == "}":
            depth = max(0, depth - 1)
            if depth == 0:
                if pending_name is not None and body_start is not None:
                    start_line = _declarator_start_line(
                        blanked, line_starts, body_start
                    )
                    end_line = _line_of(line_starts, offset)
                    functions.append(
                        FunctionRange(
                            name=pending_name,
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )
                pending_name = None
                body_start = None
            segment_start = offset + 1
        elif char == ";" and depth == 0:
            segment_start = offset + 1

    return tuple(functions)


def function_at(functions: tuple[FunctionRange, ...], line: int) -> FunctionRange | None:
    """Innermost function containing ``line``, or None."""
    best: FunctionRange | None = None
    for function in functions:
        if not function.contains(line):
            continue
        if best is None or (function.end_line - function.start_line) < (
            best.end_line - best.start_line
        ):
            best = function
    return best


def _declarator_name(text: str) -> str | None:
    """Name of the function whose body is about to open, if this is one."""
    candidate = text.strip()
    if not candidate:
        return None
    # A function-like macro whose body contains braces opens one at depth 0.
    # It is a definition, but not of a function.
    last_line = candidate.rsplit("\n", 1)[-1].lstrip()
    if last_line.startswith("#"):
        return None
    # An initialiser list, an enum body or a struct definition has no
    # parenthesised parameter list ending the declarator.
    match = _DECLARATOR.search(candidate)
    if match is None:
        return None
    name = match.group("name")
    if name in _NOT_FUNCTIONS:
        return None
    # "= {" and "struct x {" are not function bodies.
    if candidate.rstrip().endswith("="):
        return None
    return name


def _declarator_start_line(
    blanked: str, line_starts: list[int], brace_offset: int
) -> int:
    """First line of the declarator whose body opens at ``brace_offset``.

    Walks back line by line so that a signature split across several lines is
    reported from its first line, and stops at anything that cannot be part of
    a declarator: a blank line, a preprocessor directive, a label, or the end
    of a previous statement or block.
    """
    line = _line_of(line_starts, brace_offset)
    while line > 1:
        previous = _line_text(blanked, line_starts, line - 1).strip()
        if (
            not previous
            or previous.startswith("#")
            or previous.endswith((";", "}", "{", ":"))
        ):
            break
        line -= 1
    return line


def _line_text(blanked: str, line_starts: list[int], line: int) -> str:
    start = line_starts[line - 1]
    end = line_starts[line] if line < len(line_starts) else len(blanked)
    return blanked[start:end]


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_of(line_starts: list[int], offset: int) -> int:
    low, high = 0, len(line_starts) - 1
    while low <= high:
        mid = (low + high) // 2
        if line_starts[mid] <= offset:
            low = mid + 1
        else:
            high = mid - 1
    return max(1, low)
