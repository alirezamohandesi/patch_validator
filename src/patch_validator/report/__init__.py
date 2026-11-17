"""Report Generator — module 15 of the architecture."""

from .model import BuildModeObservation, RunRecord
from .writer import (
    load_schema,
    render_markdown,
    validate,
    write_json,
    write_markdown,
    write_patch_diff,
)

__all__ = [
    "BuildModeObservation",
    "RunRecord",
    "load_schema",
    "render_markdown",
    "validate",
    "write_json",
    "write_markdown",
    "write_patch_diff",
]
