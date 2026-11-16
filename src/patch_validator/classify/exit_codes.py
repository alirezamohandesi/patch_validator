"""Process exit codes.

The exit code is the whole point of running this tool in a pipeline, so the
values and their precedence live in one place and nowhere else.

Precedence comes from the official course specification, section 3.5:

    30 > 10 > 20 > 40 > 0

The implementation guide states a different order (``0 < 30 < 10 < 20 < 40``).
Where the two documents disagree the official specification wins, and the
reasoning behind its order is sound on its own terms: if the build or the
configuration is broken, no security or functional claim derived from it is
worth anything, so that condition has to outrank the rest.  See
docs/REQUIREMENTS.md conflict C-01 and docs/DESIGN_DECISIONS.md ADR-004.
"""

from __future__ import annotations

from typing import Final

PASS: Final = 0
VULN_REMAINS: Final = 10
FUNC_REGRESSION: Final = 20
BUILD_OR_CONFIG_ERROR: Final = 30
INCONCLUSIVE: Final = 40

#: Highest priority first.  When several conditions hold at once, the first
#: one in this tuple decides the process exit code.
EXIT_PRECEDENCE: Final[tuple[int, ...]] = (
    BUILD_OR_CONFIG_ERROR,
    VULN_REMAINS,
    FUNC_REGRESSION,
    INCONCLUSIVE,
    PASS,
)

EXIT_NAMES: Final[dict[int, str]] = {
    PASS: "PASS",
    VULN_REMAINS: "VULN_REMAINS_OR_NEW_ISSUE",
    FUNC_REGRESSION: "FUNC_REGRESSION",
    BUILD_OR_CONFIG_ERROR: "BUILD_OR_CONFIG_ERROR",
    INCONCLUSIVE: "INCONCLUSIVE",
}

EXIT_DESCRIPTIONS: Final[dict[int, str]] = {
    PASS: (
        "the base fault was reproduced, is not observed on the patched build, "
        "no other security finding was confirmed, every functional test passed "
        "and every mandatory check completed"
    ),
    VULN_REMAINS: (
        "the original fault still occurs, or another memory error was confirmed "
        "with valid evidence on the patched build"
    ),
    FUNC_REGRESSION: (
        "at least one input that behaved correctly on the base build violates "
        "the independent oracle on the patched build"
    ),
    BUILD_OR_CONFIG_ERROR: (
        "the target could not be built, the configuration is invalid, or the "
        "execution environment is unusable"
    ),
    INCONCLUSIVE: (
        "a mandatory check did not complete, or the evidence does not support a "
        "verdict"
    ),
}


def resolve(candidates: set[int]) -> int:
    """Pick the winning exit code from the conditions that hold."""
    for code in EXIT_PRECEDENCE:
        if code in candidates:
            return code
    return PASS


def name(code: int) -> str:
    return EXIT_NAMES.get(code, f"UNKNOWN_{code}")
