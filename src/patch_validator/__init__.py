"""Automated security patch validation and regression testing for CI/CD.

The package is organised as a set of independent modules wired together by
:mod:`patch_validator.pipeline`.  No module below the pipeline layer knows
anything about a specific target program: everything that is target specific
arrives through configuration.
"""

from __future__ import annotations

__version__ = "0.1.0"

#: Version of the JSON report schema produced by this tool.  Bump on any
#: backwards incompatible change to the report structure.
REPORT_SCHEMA_VERSION = "1.0"

#: Version of the YAML configuration schema accepted by this tool.
CONFIG_SCHEMA_VERSION = 1

__all__ = ["__version__", "REPORT_SCHEMA_VERSION", "CONFIG_SCHEMA_VERSION"]
