"""
Typed result models for the ISO 26262 Validation Engine.

All four validation checks are returned in a single ValidationResult so
the caller gets a complete, structured view of a requirement's compliance state.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TraceabilityResult:
    """Coverage of a requirement by linked test cases."""

    covered: bool
    linked_test_ids: List[str]
    missing_levels: List[str]   # ISO 26262 Part 6 test levels not yet covered
    verdict_summary: str        # e.g. "2 Pass, 1 Fail, 3 Not Run"
    notes: str = ""


@dataclass
class DefectRiskResult:
    """Defect-based risk assessment for a requirement."""

    risk_level: str             # Low | Medium | High | Critical
    open_defect_count: int
    critical_defect_ids: List[str]
    assessment: str


@dataclass
class QualityResult:
    """Textual quality and ambiguity analysis of the requirement statement."""

    score: int                  # 0-100 (higher = better)
    issues: List[str]           # detected quality problems
    suggestions: List[str]      # recommended improvements


@dataclass
class SafetyChainResult:
    """Vertical traceability through the SG → FSR → TSR → SSR hierarchy."""

    chain_complete: bool
    asil_level: str
    parent_id: Optional[str]
    children_ids: List[str]
    gaps: List[str]             # missing links or ASIL mismatches
    decomposition_valid: bool = True


@dataclass
class ValidationResult:
    """Aggregated result of all four ISO 26262 validation checks."""

    requirement_id: str
    traceability: TraceabilityResult
    defect_risk: DefectRiskResult
    quality: QualityResult
    safety_chain: SafetyChainResult
    overall_verdict: str        # Pass | Warning | Fail
    coverage_status: str        # maps to kb_ingestor.models.CoverageStatus
    raw_response: str           # raw Claude output for audit trail
    model_used: str
    timestamp: str              # ISO 8601 UTC

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)
