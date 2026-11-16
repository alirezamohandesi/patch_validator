"""Analysis modules: crash classification, oracle, correlation, hardening."""

from .crash import CrashAnalyzer, CrashInfo
from .differential import CasePair, DifferentialTester
from .findings import Finding, FindingKind
from .frames import StackFrame, parse_frames
from .hardening import HardeningAnalyzer, HardeningReport
from .oracle import OracleEvaluator, OracleVerdict
from .patch import Correlation, PatchAnalyzer
from .diffparse import PatchDiff, parse_patch

__all__ = [
    "CasePair",
    "Correlation",
    "CrashAnalyzer",
    "CrashInfo",
    "DifferentialTester",
    "Finding",
    "HardeningAnalyzer",
    "HardeningReport",
    "FindingKind",
    "OracleEvaluator",
    "OracleVerdict",
    "PatchAnalyzer",
    "PatchDiff",
    "StackFrame",
    "parse_frames",
    "parse_patch",
]
