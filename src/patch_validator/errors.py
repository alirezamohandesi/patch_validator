"""Exception hierarchy.

Every exception carries the process exit code that should be produced if it
escapes to the CLI.  Build, configuration and sandbox problems all map to 30
(``BUILD_OR_CONFIG_ERROR``): the specification is explicit that they must not
be counted the same way as a security finding.
"""

from __future__ import annotations


class PatchValidatorError(Exception):
    """Base class for every error raised by this tool."""

    #: Exit code produced when this error reaches the CLI boundary.
    exit_code: int = 30

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        #: Optional actionable hint shown to the user alongside the message.
        self.remedy = remedy


class ConfigError(PatchValidatorError):
    """The configuration file is missing, malformed or internally inconsistent."""


class VcsError(PatchValidatorError):
    """A git operation on the target repository failed."""


class BuildError(PatchValidatorError):
    """A build command failed, or produced no usable binary."""

    def __init__(
        self,
        message: str,
        *,
        remedy: str | None = None,
        log_ref: str | None = None,
    ) -> None:
        super().__init__(message, remedy=remedy)
        #: Path of the captured build log, relative to the run artifact root.
        self.log_ref = log_ref


class SandboxUnavailable(PatchValidatorError):
    """No isolated execution environment is available.

    Raised instead of silently falling back to unisolated execution: running a
    known-vulnerable binary without isolation is never an acceptable default.
    """


class ExecutionError(PatchValidatorError):
    """The target could not be launched at all (as opposed to crashing)."""


class ReportError(PatchValidatorError):
    """The produced report failed its own schema validation."""
