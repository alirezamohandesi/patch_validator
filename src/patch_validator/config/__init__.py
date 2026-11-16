"""Configuration Manager — module 1 of the architecture."""

from .loader import load_config
from .models import (
    VERSIONS,
    BuildMode,
    BuildSpec,
    InputSpec,
    Limits,
    MinimizationSpec,
    OracleSpec,
    OutputMatcher,
    ReproductionSpec,
    SandboxSpec,
    TargetSpec,
    TestCase,
    ValidationConfig,
    Version,
)

__all__ = [
    "VERSIONS",
    "BuildMode",
    "BuildSpec",
    "InputSpec",
    "Limits",
    "MinimizationSpec",
    "OracleSpec",
    "OutputMatcher",
    "ReproductionSpec",
    "SandboxSpec",
    "TargetSpec",
    "TestCase",
    "ValidationConfig",
    "Version",
    "load_config",
]
