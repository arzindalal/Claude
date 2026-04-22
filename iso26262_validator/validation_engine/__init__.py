"""
ISO 26262 Validation Engine — Phase 2.

Public surface:
    ValidationEngine  — orchestrates RAG context + Claude calls + DB writes
    ValidationResult  — typed result returned per requirement
"""

from .result_models import (
    DefectRiskResult,
    QualityResult,
    SafetyChainResult,
    TraceabilityResult,
    ValidationResult,
)
from .validator import ValidationEngine

__all__ = [
    "ValidationEngine",
    "ValidationResult",
    "TraceabilityResult",
    "DefectRiskResult",
    "QualityResult",
    "SafetyChainResult",
]
