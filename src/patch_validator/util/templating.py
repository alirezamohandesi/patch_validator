"""Placeholder substitution for configuration-supplied commands.

Build and execution commands come from configuration, which is what keeps the
tool target agnostic (R-SCOPE-08).  Those commands need to reference paths the
tool computes at runtime, so they may contain ``{placeholder}`` tokens.

Substitution is deliberately *not* ``str.format``: compiler flag strings
routinely contain braces, and an accidental ``KeyError`` or silent reformat of
a flag would be hard to debug.  Only ``{identifier}`` tokens whose name is a
known placeholder are replaced; anything else is passed through untouched.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence

from ..errors import ConfigError

_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(template: str, values: Mapping[str, str]) -> str:
    """Replace known ``{placeholder}`` tokens in ``template``."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values:
            return str(values[name])
        return match.group(0)

    return _TOKEN.sub(substitute, template)


def unknown_placeholders(template: str, allowed: Sequence[str]) -> list[str]:
    """Return the placeholder names in ``template`` that are not ``allowed``."""
    return sorted({name for name in _TOKEN.findall(template) if name not in allowed})


def render_argv(
    command: str | Sequence[str],
    values: Mapping[str, str],
    *,
    context: str = "command",
) -> list[str]:
    """Render a configured command into an argv list.

    A command may be written either as a list of arguments or as a single
    string.  Strings are split with POSIX shell rules *before* substitution, so
    a path containing spaces cannot change the shape of the command.  No shell
    is ever involved.
    """
    if isinstance(command, str):
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise ConfigError(f"{context}: cannot parse {command!r}: {exc}") from exc
    else:
        parts = [str(part) for part in command]

    if not parts:
        raise ConfigError(f"{context}: empty command")

    rendered = [render(part, values) for part in parts]
    # Dropping empty arguments keeps optional flag slots such as
    # "{ldflags}" from turning into a stray empty argv entry.
    return [part for part in rendered if part != ""]
