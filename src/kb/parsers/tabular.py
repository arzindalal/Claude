"""
Parsers for CSV / Excel artefact exports.

All parsers return typed Pydantic records. Column names are case-insensitive
and whitespace-tolerant; synonym sets handle the common export conventions
(Cradle vs. DOORS vs. hand-rolled Excel).

Unknown columns are ignored. Required columns that are missing raise a clear
exception — silent drops would defeat the point of a validation tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from src.kb.models import (
    ASIL,
    Defect,
    DefectStatus,
    Requirement,
    ReqLevel,
    TestCase,
    TestLevel,
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _load(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df.fillna("")


def _pick(row: pd.Series, *candidates: str, default: str = "") -> str:
    for c in candidates:
        if c in row.index and str(row[c]).strip():
            return str(row[c]).strip()
    return default


def _split_ids(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

_LEVEL_MAP = {
    "customer": ReqLevel.CUSTOMER, "cust": ReqLevel.CUSTOMER,
    "system": ReqLevel.SYSTEM, "sys": ReqLevel.SYSTEM,
    "software": ReqLevel.SW, "sw": ReqLevel.SW,
    "hardware": ReqLevel.HW, "hw": ReqLevel.HW,
    "safety_goal": ReqLevel.SAFETY_GOAL, "sg": ReqLevel.SAFETY_GOAL,
    "tsr": ReqLevel.TSR, "technical_safety_requirement": ReqLevel.TSR,
    "ssr": ReqLevel.SSR, "software_safety_requirement": ReqLevel.SSR,
}

_ASIL_MAP = {
    "": ASIL.QM, "qm": ASIL.QM,
    "a": ASIL.A, "asil-a": ASIL.A, "asil_a": ASIL.A,
    "b": ASIL.B, "asil-b": ASIL.B, "asil_b": ASIL.B,
    "c": ASIL.C, "asil-c": ASIL.C, "asil_c": ASIL.C,
    "d": ASIL.D, "asil-d": ASIL.D, "asil_d": ASIL.D,
}


def parse_requirements(path: Path) -> list[Requirement]:
    df = _load(path)
    out: list[Requirement] = []
    for _, row in df.iterrows():
        rid = _pick(row, "id", "req_id", "requirement_id", "identifier")
        if not rid:
            continue
        level_raw = _pick(row, "level", "type", "requirement_type", default="system").lower()
        level = _LEVEL_MAP.get(level_raw, ReqLevel.SYSTEM)
        asil_raw = _pick(row, "asil", "safety_level").lower()
        asil = _ASIL_MAP.get(asil_raw, ASIL.QM)
        tags = _split_ids(_pick(row, "tags", "labels"))
        out.append(Requirement(
            id=rid,
            level=level,
            title=_pick(row, "title", "name", "summary", default=rid),
            text=_pick(row, "text", "description", "requirement_text", "statement"),
            asil=asil,
            parent_id=_pick(row, "parent_id", "derived_from", "parent") or None,
            source=str(path),
            tags=tags,
        ))
    return out


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

_TEST_LEVEL_MAP = {
    "unit": TestLevel.UNIT, "ut": TestLevel.UNIT,
    "integration": TestLevel.INTEGRATION, "it": TestLevel.INTEGRATION,
    "system": TestLevel.SYSTEM, "st": TestLevel.SYSTEM,
    "acceptance": TestLevel.ACCEPTANCE, "uat": TestLevel.ACCEPTANCE,
    "validation": TestLevel.VALIDATION, "val": TestLevel.VALIDATION,
}


def parse_test_cases(path: Path) -> list[TestCase]:
    df = _load(path)
    out: list[TestCase] = []
    for _, row in df.iterrows():
        tid = _pick(row, "id", "test_id", "tc_id")
        if not tid:
            continue
        level_raw = _pick(row, "level", "test_level", default="system").lower()
        level = _TEST_LEVEL_MAP.get(level_raw, TestLevel.SYSTEM)
        out.append(TestCase(
            id=tid,
            title=_pick(row, "title", "name", default=tid),
            level=level,
            objective=_pick(row, "objective", "purpose", "description"),
            preconditions=_pick(row, "preconditions", "setup"),
            steps=_pick(row, "steps", "procedure", "test_steps"),
            expected_result=_pick(row, "expected_result", "expected", "pass_criteria"),
            verifies_req_ids=_split_ids(
                _pick(row, "verifies", "verifies_req_ids", "traces_to", "req_ids")
            ),
            asil_coverage_hint=_pick(row, "asil_coverage_hint", "coverage"),
            source=str(path),
        ))
    return out


# ---------------------------------------------------------------------------
# Defects
# ---------------------------------------------------------------------------

_DEFECT_STATUS_MAP = {
    "open": DefectStatus.OPEN, "new": DefectStatus.OPEN,
    "in_progress": DefectStatus.IN_PROGRESS, "in progress": DefectStatus.IN_PROGRESS,
    "wip": DefectStatus.IN_PROGRESS,
    "fixed": DefectStatus.FIXED, "resolved": DefectStatus.FIXED,
    "verified": DefectStatus.VERIFIED,
    "closed": DefectStatus.CLOSED, "done": DefectStatus.CLOSED,
    "rejected": DefectStatus.REJECTED, "wontfix": DefectStatus.REJECTED,
}


def parse_defects(path: Path) -> list[Defect]:
    df = _load(path)
    out: list[Defect] = []
    for _, row in df.iterrows():
        did = _pick(row, "id", "defect_id", "issue_id", "key")
        if not did:
            continue
        status_raw = _pick(row, "status", "state", default="open").lower()
        status = _DEFECT_STATUS_MAP.get(status_raw, DefectStatus.OPEN)
        out.append(Defect(
            id=did,
            title=_pick(row, "title", "summary", default=did),
            description=_pick(row, "description", "details"),
            status=status,
            severity=_pick(row, "severity", "priority"),
            against_req_ids=_split_ids(_pick(row, "against_req_ids", "req_ids", "affects_req")),
            against_test_ids=_split_ids(_pick(row, "against_test_ids", "test_ids", "affects_test")),
            source=str(path),
        ))
    return out


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, callable] = {
    "requirements": parse_requirements,
    "test_cases": parse_test_cases,
    "tests": parse_test_cases,
    "defects": parse_defects,
    "issues": parse_defects,
}


def classify(path: Path) -> str:
    """Classify a file by stem — `requirements.csv`, `test_cases.xlsx`, ..."""
    stem = path.stem.lower()
    for key in _DISPATCH:
        if key in stem:
            return key
    return ""


def parse_any(path: Path) -> Iterable:
    kind = classify(path)
    if not kind:
        raise ValueError(f"Could not classify artefact file from stem: {path.name}")
    return _DISPATCH[kind](path)
