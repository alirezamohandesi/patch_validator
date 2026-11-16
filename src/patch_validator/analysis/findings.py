"""Findings produced by the differential comparison."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .crash import CrashInfo
from .oracle import OracleVerdict
from .patch import Correlation

Axis = Literal["security", "functional", "completeness"]

FindingKind = Literal[
    # security axis
    "FIXED",
    "INCOMPLETE_FIX",
    "NEW_ISSUE",
    # functional axis
    "FUNCTIONAL_REGRESSION",
    "FUNCTIONAL_FIX",
    "PRE_EXISTING_DEFECT",
    # either axis, when the evidence does not support a conclusion
    "INCONCLUSIVE",
    # completeness axis
    "MISSING_ORACLE",
    "RESOURCE_LIMIT",
    "ANALYSIS_GAP",
]

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Finding:
    """One conclusion about one test case in one build mode."""

    id: str
    axis: Axis
    kind: FindingKind
    test_id: str
    build_mode: str
    summary: str
    confidence: Confidence = "high"

    base_behavior: str = ""
    patched_behavior: str = ""
    base_crash: CrashInfo | None = None
    patched_crash: CrashInfo | None = None
    base_oracle: OracleVerdict | None = None
    patched_oracle: OracleVerdict | None = None

    #: Set for INCOMPLETE_FIX when the fault moved to a different location.
    signature_changed: bool = False
    #: Only release-mode functional findings decide the verdict; sanitized
    #: ones are recorded for information because instrumentation changes
    #: timing and output (ADR-008).
    authoritative: bool = True
    correlation: Correlation | None = None
    notes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_security_problem(self) -> bool:
        """Whether this finding means the patched build is still unsafe."""
        return self.kind in ("INCOMPLETE_FIX", "NEW_ISSUE")

    def with_correlation(self, correlation: Correlation) -> Finding:
        from dataclasses import replace

        return replace(self, correlation=correlation)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "axis": self.axis,
            "kind": self.kind,
            "test_id": self.test_id,
            "build_mode": self.build_mode,
            "summary": self.summary,
            "confidence": self.confidence,
            "authoritative": self.authoritative,
            "base_behavior": self.base_behavior,
            "patched_behavior": self.patched_behavior,
            "signature_changed": self.signature_changed,
            "base_crash": self.base_crash.to_dict() if self.base_crash else None,
            "patched_crash": (
                self.patched_crash.to_dict() if self.patched_crash else None
            ),
            "base_oracle": self.base_oracle.to_dict() if self.base_oracle else None,
            "patched_oracle": (
                self.patched_oracle.to_dict() if self.patched_oracle else None
            ),
            "correlation": self.correlation.to_dict() if self.correlation else None,
            "notes": list(self.notes),
            "evidence_refs": list(self.evidence_refs),
        }
